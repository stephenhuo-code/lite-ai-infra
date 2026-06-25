# tests/scaffold/test_auth.py
import json
from fastapi import FastAPI, Depends, Request
from fastapi.testclient import TestClient
from services._scaffold.auth import context_from_request
from libs.identity.context import Context

def _app():
    app = FastAPI()
    @app.get("/who")
    def who(ctx: Context = Depends(context_from_request)):
        ent = ctx.memberships[0].enterprise_id if ctx.memberships else None
        return {"user": ctx.user, "n": len(ctx.memberships),
                "role": ctx.role_in(ent) if ent else None}
    return app

def test_test_claims_seam_off_by_default(monkeypatch):
    monkeypatch.delenv("LITEAI_ALLOW_TEST_CLAIMS", raising=False)
    c = TestClient(_app())
    r = c.get("/who", headers={"x-test-claims": json.dumps({"sub": "u", "organization": []})})
    assert r.status_code == 401

def test_test_claims_seam_on_carries_organization_and_role(monkeypatch):
    monkeypatch.setenv("LITEAI_ALLOW_TEST_CLAIMS", "1")
    c = TestClient(_app())
    r = c.get("/who", headers={"x-test-claims": json.dumps(
        {"sub": "u-a", "organization": ["ent-demo"], "realm_roles": ["enterprise-admin"]})})
    assert r.status_code == 200
    assert r.json() == {"user": "u-a", "n": 1, "role": "enterprise-admin"}

def test_test_claims_organization_str_coerced(monkeypatch):
    # KC multivalued=false 时 organization 为单字符串 → 归一为单成员
    monkeypatch.setenv("LITEAI_ALLOW_TEST_CLAIMS", "1")
    c = TestClient(_app())
    r = c.get("/who", headers={"x-test-claims": json.dumps(
        {"sub": "u-a", "organization": "ent-demo", "realm_roles": []})})
    assert r.status_code == 200 and r.json() == {"user": "u-a", "n": 1, "role": "member"}

def test_no_bearer_401(monkeypatch):
    monkeypatch.delenv("LITEAI_ALLOW_TEST_CLAIMS", raising=False)
    assert TestClient(_app()).get("/who").status_code == 401

def test_jwt_path_reads_organization_and_realm_access(monkeypatch):
    # 真 JWT 路径:KC token 顶层 organization(alias 数组)+ realm_access.roles
    monkeypatch.delenv("LITEAI_ALLOW_TEST_CLAIMS", raising=False)
    monkeypatch.setenv("LITEAI_JWKS_URL", "http://kc/certs")
    import services._scaffold.auth as auth
    monkeypatch.setattr(auth, "verify_and_decode", lambda *a, **k: {
        "sub": "u-a", "organization": ["ent-demo"],
        "realm_access": {"roles": ["enterprise-admin", "offline_access"]}})
    r = TestClient(_app()).get("/who", headers={"authorization": "Bearer tok"})
    assert r.status_code == 200
    assert r.json() == {"user": "u-a", "n": 1, "role": "enterprise-admin"}
