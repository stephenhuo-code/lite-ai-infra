# tests/gateway/bff/test_session_mw.py —— Task 5:会话中间件 + bearer 注入 + 刷新 + /auth/me(TDD)
# 命门:C-1(客户端伪造 bearer 绝不绕过会话)、C-2(刷新随当前响应 Set-Cookie)、I-1(single-flight)、I-4(刷新失败清 cookie+401)、M-3(/auth/me)
import asyncio
import time

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import Request
from fastapi.testclient import TestClient

from services._scaffold.app import make_service_app
from services.gateway.app import build_gateway
from services.gateway.bff.middleware import RefreshCoordinator, install_bff
from services.gateway.bff.session import SESSION_COOKIE, SessionCodec, SessionData

KEY = Fernet.generate_key()


def _downstream():
    app = make_service_app("ds", "0.1.0")

    @app.api_route("/v1/data/echo", methods=["GET", "POST"])
    async def echo(request: Request):
        return {"auth": request.headers.get("authorization")}

    return app


def _claims(_token):
    return {"sub": "u-alice", "organization": ["ent-demo"],
            "realm_access": {"roles": ["member"]},
            "preferred_username": "alice", "email": "alice@example.com"}


def _env(monkeypatch):
    monkeypatch.setenv("BFF_SESSION_KEY", KEY.decode())
    monkeypatch.setenv("OIDC_CLIENT_ID", "lite-ai-web")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "s")
    monkeypatch.setenv("OIDC_ISSUER", "http://kc/realms/x")
    monkeypatch.setenv("BFF_REDIRECT_URI", "http://gw/auth/callback")


def _app(monkeypatch, *, refresh_fn=None, claims_fn=_claims):
    _env(monkeypatch)
    ds = _downstream()
    transport = httpx.ASGITransport(app=ds)
    app = build_gateway(routes={
        "/v1/data": ("http://ds", lambda: httpx.AsyncClient(transport=transport, base_url="http://ds")),
    })
    install_bff(app, refresh_fn=refresh_fn or (lambda rt: {"access_token": "at-new", "refresh_token": "rt2", "expires_in": 300}),
                claims_fn=claims_fn)
    return app


def _cookie(sd: SessionData) -> str:
    return SessionCodec(KEY).encode(sd)


def _valid_sd():
    return SessionData("at-alice", "rt", int(time.time()) + 300, csrf="csrf-xyz")


# ---- bearer 注入 / 401 ----

def test_valid_session_injects_bearer_downstream(monkeypatch):
    c = TestClient(_app(monkeypatch))
    r = c.get("/v1/data/echo", cookies={SESSION_COOKIE: _cookie(_valid_sd())})
    assert r.status_code == 200 and r.json()["auth"] == "Bearer at-alice"


def test_no_session_protected_401(monkeypatch):
    assert TestClient(_app(monkeypatch)).get("/v1/data/echo").status_code == 401


# ---- C-1 红线负向 ----

def test_forged_bearer_no_session_401(monkeypatch):
    # 伪造 Authorization + 无会话 cookie → 401,绝不把 forged 透传给下游
    c = TestClient(_app(monkeypatch))
    r = c.get("/v1/data/echo", headers={"Authorization": "Bearer forged"})
    assert r.status_code == 401


def test_forged_bearer_with_session_uses_session_access(monkeypatch):
    # 有会话 + 客户端同时带伪造 Authorization → 下游收到的是会话 access(非 forged)
    c = TestClient(_app(monkeypatch))
    r = c.get("/v1/data/echo", headers={"Authorization": "Bearer forged"},
              cookies={SESSION_COOKIE: _cookie(_valid_sd())})
    assert r.status_code == 200 and r.json()["auth"] == "Bearer at-alice"


# ---- C-2 刷新随当前响应下发 ----

def test_expired_access_refreshes_and_sets_cookie(monkeypatch):
    c = TestClient(_app(monkeypatch))
    expired = SessionData("at-old", "rt", int(time.time()) - 10, csrf="csrf-xyz")
    r = c.get("/v1/data/echo", cookies={SESSION_COOKIE: _cookie(expired)})
    assert r.status_code == 200 and r.json()["auth"] == "Bearer at-new"   # 下游收到刷新后的新 access
    sc = r.headers.get("set-cookie", "")
    assert "session=" in sc                                               # 当前响应带 Set-Cookie
    # 新 cookie 解出新 access
    new = c.cookies.get(SESSION_COOKIE)
    assert SessionCodec(KEY).decode(new).access_token == "at-new"


# ---- I-4 刷新失败 → 清 cookie + 401 ----

def test_refresh_failure_clears_cookie_and_401(monkeypatch):
    def boom(rt):
        raise RuntimeError("refresh rejected")

    c = TestClient(_app(monkeypatch, refresh_fn=boom))
    expired = SessionData("at-old", "rt", int(time.time()) - 10, csrf="csrf-xyz")
    r = c.get("/v1/data/echo", cookies={SESSION_COOKIE: _cookie(expired)})
    assert r.status_code == 401
    sc = r.headers.get("set-cookie", "")
    assert "session=" in sc and "Max-Age=0" in sc                        # 清会话 cookie


# ---- M-3 /auth/me ----

def test_auth_me_returns_user_and_csrf(monkeypatch):
    c = TestClient(_app(monkeypatch))
    r = c.get("/auth/me", cookies={SESSION_COOKIE: _cookie(_valid_sd())})
    assert r.status_code == 200
    body = r.json()
    assert body["user"] == "u-alice" and body["is_platform_admin"] is False and body["csrf"] == "csrf-xyz"
    assert body["username"] == "alice" and body["email"] == "alice@example.com"  # 真实展示信息
    assert body["enterprises"] == ["ent-demo"]  # 企业归属来自 organization claim(alias)


def test_auth_me_no_session_401(monkeypatch):
    assert TestClient(_app(monkeypatch)).get("/auth/me").status_code == 401


# ---- I-1 single-flight:并发同 refresh token 只刷一次,后到者复用 ----

def test_refresh_coordinator_single_flight():
    calls = []

    def slow_refresh(rt):
        calls.append(rt)
        time.sleep(0.05)
        return {"access_token": "new", "refresh_token": "rt2", "expires_in": 300}

    coord = RefreshCoordinator(slow_refresh)

    async def go():
        return await asyncio.gather(coord.refresh("rt"), coord.refresh("rt"), coord.refresh("rt"))

    results = asyncio.run(go())
    assert len(calls) == 1                          # 同一旧 refresh 只真刷一次(double-check 复用)
    assert all(r["access_token"] == "new" for r in results)


def test_refresh_coordinator_failure_clears_lock_and_allows_retry():
    # I-4 + 防泄漏:刷新失败不缓存、清掉本 key 锁;同 key 可重试(不被失败锁卡死)。
    attempts = []

    def flaky(rt):
        attempts.append(rt)
        if len(attempts) == 1:
            raise RuntimeError("first fails")
        return {"access_token": "ok", "refresh_token": "rt2", "expires_in": 300}

    coord = RefreshCoordinator(flaky)

    async def go():
        try:
            await coord.refresh("rt")
        except RuntimeError:
            pass
        assert "rt" not in coord._locks            # 失败后锁已清(不泄漏)
        return await coord.refresh("rt")           # 重试成功(未被失败锁卡死)

    r = asyncio.run(go())
    assert r["access_token"] == "ok" and len(attempts) == 2
