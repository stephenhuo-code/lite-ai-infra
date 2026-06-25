# tests/gateway/bff/test_orgs_invite.py —— 企业邀请端点(enterprise-admin)+ KC inviter 契约
import time

import httpx
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from services.gateway.app import build_gateway
from services.gateway.bff.middleware import install_bff
from services.gateway.bff.orgs import OrgInviter
from services.gateway.bff.session import SESSION_COOKIE, SessionCodec, SessionData

KEY = Fernet.generate_key()


def _env(monkeypatch):
    monkeypatch.setenv("BFF_SESSION_KEY", KEY.decode())
    monkeypatch.setenv("OIDC_CLIENT_ID", "lite-ai-web")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "s")
    monkeypatch.setenv("OIDC_ISSUER", "http://kc/realms/x")
    monkeypatch.setenv("BFF_REDIRECT_URI", "http://gw/auth/callback")


class FakeInviter:
    def __init__(self):
        self.calls = []

    def invite(self, org_alias, email):
        self.calls.append((org_alias, email))


def _admin_claims(_t):
    return {"sub": "u-admin", "organization": ["ent-demo"],
            "realm_access": {"roles": ["enterprise-admin"]}}


def _member_claims(_t):
    return {"sub": "u-mem", "organization": ["ent-demo"],
            "realm_access": {"roles": ["member"]}}


def _app(monkeypatch, *, claims_fn, inviter):
    _env(monkeypatch)
    app = build_gateway(routes={})
    install_bff(app, claims_fn=claims_fn, inviter=inviter,
                refresh_fn=lambda rt: {"access_token": "at", "refresh_token": "rt", "expires_in": 300})
    return app


def _sd():
    return SessionData("at", "rt", int(time.time()) + 300, csrf="csrf-xyz")


def _cookie():
    return SessionCodec(KEY).encode(_sd())


def test_enterprise_admin_can_invite(monkeypatch):
    inv = FakeInviter()
    c = TestClient(_app(monkeypatch, claims_fn=_admin_claims, inviter=inv))
    r = c.post("/auth/orgs/invite", json={"email": "newhire@x.com"},
               headers={"x-csrf-token": "csrf-xyz"}, cookies={SESSION_COOKIE: _cookie()})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert inv.calls == [("ent-demo", "newhire@x.com")]   # 转发到 caller 的 org


def test_member_cannot_invite_403(monkeypatch):
    inv = FakeInviter()
    c = TestClient(_app(monkeypatch, claims_fn=_member_claims, inviter=inv))
    r = c.post("/auth/orgs/invite", json={"email": "x@x.com"},
               headers={"x-csrf-token": "csrf-xyz"}, cookies={SESSION_COOKIE: _cookie()})
    assert r.status_code == 403
    assert inv.calls == []                                  # 非 admin → 零副作用


def test_invite_without_csrf_403(monkeypatch):
    inv = FakeInviter()
    c = TestClient(_app(monkeypatch, claims_fn=_admin_claims, inviter=inv))
    r = c.post("/auth/orgs/invite", json={"email": "x@x.com"},
               cookies={SESSION_COOKIE: _cookie()})       # 无 X-CSRF-Token
    assert r.status_code == 403
    assert inv.calls == []


def test_invite_unauthenticated_403_or_401(monkeypatch):
    inv = FakeInviter()
    c = TestClient(_app(monkeypatch, claims_fn=_admin_claims, inviter=inv))
    r = c.post("/auth/orgs/invite", json={"email": "x@x.com"})  # 无会话、无 CSRF
    assert r.status_code in (401, 403)
    assert inv.calls == []


# ---- OrgInviter 契约级:alias → id → invite-user ----

def test_inviter_forwards_to_kc_invite_user():
    seen = {}

    def h(req):
        if req.url.path.endswith("/realms/master/protocol/openid-connect/token"):
            return httpx.Response(200, json={"access_token": "adm"})
        if req.method == "GET" and req.url.path.endswith("/organizations"):
            return httpx.Response(200, json=[{"id": "org-1", "alias": "ent-demo"}])
        if req.method == "POST" and req.url.path.endswith("/members/invite-user"):
            seen["path"] = req.url.path
            seen["body"] = req.read().decode()
            return httpx.Response(204)
        raise AssertionError(f"unexpected {req.method} {req.url}")

    OrgInviter(base_url="http://kc", transport=httpx.MockTransport(h)).invite("ent-demo", "a@b.com")
    assert seen["path"].endswith("/organizations/org-1/members/invite-user")
    assert "a%40b.com" in seen["body"] or "a@b.com" in seen["body"]
