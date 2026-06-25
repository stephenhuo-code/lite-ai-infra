# tests/integration/test_gateway_proxy.py
import socket
import time

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration

KC = "http://localhost:8080/realms/lite-ai"
JWKS = f"{KC}/protocol/openid-connect/certs"
KEY = Fernet.generate_key()


def _kc_up() -> bool:
    try:
        with socket.create_connection(("localhost", 8080), timeout=1):
            return True
    except OSError:
        return False


def _ropc() -> str:
    r = httpx.post(f"{KC}/protocol/openid-connect/token",
                   data={"client_id": "gateway", "client_secret": "dev-secret",
                         "username": "alice", "password": "alice", "grant_type": "password"})
    r.raise_for_status()
    return r.json()["access_token"]


def _gw_with_identity(monkeypatch, *, allow_test_claims: bool):
    monkeypatch.setenv("LITEAI_JWKS_URL", JWKS)
    monkeypatch.setenv("BFF_SESSION_KEY", KEY.decode())
    monkeypatch.setenv("OIDC_CLIENT_ID", "lite-ai-web")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "dev-web-secret")
    monkeypatch.setenv("OIDC_ISSUER", KC)
    monkeypatch.setenv("BFF_REDIRECT_URI", "http://localhost:8090/auth/callback")
    if allow_test_claims:
        monkeypatch.setenv("LITEAI_ALLOW_TEST_CLAIMS", "1")     # 下游**会**认 x-test-claims(若收到)
    else:
        monkeypatch.delenv("LITEAI_ALLOW_TEST_CLAIMS", raising=False)
    from services._scaffold.app import install_request_id
    from services.gateway.app import build_gateway
    from services.gateway.bff.middleware import install_bff
    from services.identity_org_service.app import app as identity_app
    transport = httpx.ASGITransport(app=identity_app)
    gw = build_gateway(routes={
        "/v1/me": ("http://id", lambda: httpx.AsyncClient(transport=transport, base_url="http://id")),
    }, with_request_id=False)
    install_bff(gw)
    install_request_id(gw)
    return gw


def _with_session(gw):
    from services.gateway.bff.session import SESSION_COOKIE, SessionCodec, SessionData
    c = TestClient(gw)
    c.cookies.set(SESSION_COOKIE, SessionCodec(KEY).encode(
        SessionData(_ropc(), None, int(time.time()) + 300, csrf="x")))
    return c


def test_gateway_to_identity_end_to_end_via_bff(monkeypatch):
    """BFF 网关:会话(真 token)→ 注入 bearer → identity-org 真验签返回 memberships。"""
    if not _kc_up():
        pytest.skip("Keycloak 未启动(先 `make up`)")
    c = _with_session(_gw_with_identity(monkeypatch, allow_test_claims=False))
    r = c.get("/v1/me/orgs")
    assert r.status_code == 200
    assert r.json()["memberships"][0]["enterprise_id"] == "e-0001"


def test_gateway_strips_client_x_test_claims(monkeypatch):
    """C-1 红线:即便下游开了 LITEAI_ALLOW_TEST_CLAIMS,客户端经 gateway 伪造 x-test-claims
    也**不被透传** —— 返回的是会话真 token 的身份(e-0001),不是伪造的 e-9999。"""
    if not _kc_up():
        pytest.skip("Keycloak 未启动(先 `make up`)")
    c = _with_session(_gw_with_identity(monkeypatch, allow_test_claims=True))
    r = c.get("/v1/me/orgs",
              headers={"x-test-claims": '{"sub":"evil","organization":["e-9999"],"realm_roles":[]}'})
    assert r.status_code == 200
    assert r.json()["memberships"][0]["enterprise_id"] == "e-0001"     # 真 token,非伪造
    assert all(m["enterprise_id"] != "e-9999" for m in r.json()["memberships"])
