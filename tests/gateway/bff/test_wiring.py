# tests/gateway/bff/test_wiring.py —— Task 8:中间件次序守护(C-2:request-id 最外 / session 内层)
# 镜像 main.py 的装配顺序,断言相对次序 —— 防回归把 request-id 排到 session 内层。
import time

import httpx
from cryptography.fernet import Fernet
from fastapi import Request
from fastapi.testclient import TestClient

from services._scaffold.app import install_request_id, make_service_app
from services.gateway.app import build_gateway
from services.gateway.bff.middleware import install_bff
from services.gateway.bff.session import SESSION_COOKIE, SessionCodec, SessionData

KEY = Fernet.generate_key()


def _downstream():
    app = make_service_app("ds", "0.1.0")

    @app.api_route("/v1/data/echo", methods=["GET"])
    async def echo(request: Request):
        return {"auth": request.headers.get("authorization")}

    return app


def _app_like_main(monkeypatch):
    monkeypatch.setenv("BFF_SESSION_KEY", KEY.decode())
    monkeypatch.setenv("OIDC_CLIENT_ID", "lite-ai-web")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "s")
    monkeypatch.setenv("OIDC_ISSUER", "http://kc/realms/x")
    monkeypatch.setenv("BFF_REDIRECT_URI", "http://gw/auth/callback")
    ds = _downstream()
    transport = httpx.ASGITransport(app=ds)
    # === 与 main.py 同序 ===
    app = build_gateway(routes={
        "/v1/data": ("http://ds", lambda: httpx.AsyncClient(transport=transport, base_url="http://ds")),
    }, with_request_id=False)
    install_bff(app, refresh_fn=lambda rt: {}, claims_fn=lambda t: {"sub": "u-alice", "groups": []})
    install_request_id(app)
    return app


def test_request_id_wraps_session_even_on_401(monkeypatch):
    # 无会话 → session 中间件在 call_next 前返 401。若 request-id 在**外层**,该 401 仍经它 → 带 x-request-id。
    # 若次序反了(request-id 内层),session 早返回时 request-id 不执行 → 无该头(本测试即失败)。
    c = TestClient(_app_like_main(monkeypatch))
    r = c.get("/v1/data/echo")
    assert r.status_code == 401
    assert "x-request-id" in r.headers          # ✅ request-id 最外,包住 session 的早返回


def test_session_injects_bearer_through_full_stack(monkeypatch):
    # 全栈(request-id→session→proxy)下,会话 bearer 正常注入下游 + 响应带 x-request-id。
    c = TestClient(_app_like_main(monkeypatch))
    c.cookies.set(SESSION_COOKIE, SessionCodec(KEY).encode(
        SessionData("at-alice", "rt", int(time.time()) + 300, csrf="x")))
    r = c.get("/v1/data/echo")
    assert r.status_code == 200 and r.json()["auth"] == "Bearer at-alice"
    assert "x-request-id" in r.headers
