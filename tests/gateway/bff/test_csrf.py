# tests/gateway/bff/test_csrf.py —— Task 6:CSRF 双提交(变更方法需 X-CSRF-Token == 会话内 csrf)
import time

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import Request
from fastapi.testclient import TestClient

from services._scaffold.app import make_service_app
from services.gateway.app import build_gateway
from services.gateway.bff.middleware import install_bff
from services.gateway.bff.session import SESSION_COOKIE, SessionCodec, SessionData

KEY = Fernet.generate_key()
CSRF = "csrf-xyz"


def _downstream():
    app = make_service_app("ds", "0.1.0")

    @app.api_route("/v1/data/echo", methods=["GET", "POST"])
    async def echo(request: Request):
        return {"auth": request.headers.get("authorization")}

    return app


def _app(monkeypatch):
    monkeypatch.setenv("BFF_SESSION_KEY", KEY.decode())
    monkeypatch.setenv("OIDC_CLIENT_ID", "lite-ai-web")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "s")
    monkeypatch.setenv("OIDC_ISSUER", "http://kc/realms/x")
    monkeypatch.setenv("BFF_REDIRECT_URI", "http://gw/auth/callback")
    ds = _downstream()
    transport = httpx.ASGITransport(app=ds)
    app = build_gateway(routes={
        "/v1/data": ("http://ds", lambda: httpx.AsyncClient(transport=transport, base_url="http://ds")),
    })
    install_bff(app, refresh_fn=lambda rt: {}, claims_fn=lambda t: {"sub": "u-alice", "groups": []})
    return app


def _client(monkeypatch):
    c = TestClient(_app(monkeypatch))
    c.cookies.set(SESSION_COOKIE, SessionCodec(KEY).encode(
        SessionData("at-alice", "rt", int(time.time()) + 300, csrf=CSRF)))
    return c


@pytest.mark.parametrize("method", ["post", "put", "delete", "patch"])
def test_mutating_missing_csrf_403(monkeypatch, method):
    c = _client(monkeypatch)
    assert getattr(c, method)("/v1/data/echo").status_code == 403


def test_mutating_wrong_csrf_403(monkeypatch):
    c = _client(monkeypatch)
    assert c.post("/v1/data/echo", headers={"X-CSRF-Token": "wrong"}).status_code == 403


def test_mutating_matching_csrf_passes(monkeypatch):
    c = _client(monkeypatch)
    r = c.post("/v1/data/echo", headers={"X-CSRF-Token": CSRF})
    assert r.status_code == 200 and r.json()["auth"] == "Bearer at-alice"


def test_get_exempt(monkeypatch):
    c = _client(monkeypatch)
    assert c.get("/v1/data/echo").status_code == 200       # GET 豁免,无需 csrf


def test_logout_requires_csrf(monkeypatch):
    c = _client(monkeypatch)
    assert c.post("/auth/logout").status_code == 403        # C-3:logout(POST)需 CSRF
    r = c.post("/auth/logout", headers={"X-CSRF-Token": CSRF})
    assert r.status_code == 200


def test_login_exempt_from_csrf(monkeypatch):
    # /auth/login(GET)天然豁免:无 csrf 仍 302
    c = TestClient(_app(monkeypatch))
    assert c.get("/auth/login", follow_redirects=False).status_code == 302
