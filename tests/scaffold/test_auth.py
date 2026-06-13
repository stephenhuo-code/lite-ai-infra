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
        return {"user": ctx.user, "n": len(ctx.memberships)}
    return app

def test_test_claims_seam_off_by_default(monkeypatch):
    monkeypatch.delenv("LITEAI_ALLOW_TEST_CLAIMS", raising=False)
    c = TestClient(_app())
    r = c.get("/who", headers={"x-test-claims": json.dumps({"sub": "u", "groups": []})})
    assert r.status_code == 401

def test_test_claims_seam_on_when_enabled(monkeypatch):
    monkeypatch.setenv("LITEAI_ALLOW_TEST_CLAIMS", "1")
    c = TestClient(_app())
    r = c.get("/who", headers={"x-test-claims": json.dumps({"sub": "u-a", "groups": ["/e-0001/g-0001/members"]})})
    assert r.status_code == 200 and r.json() == {"user": "u-a", "n": 1}

def test_no_bearer_401(monkeypatch):
    monkeypatch.delenv("LITEAI_ALLOW_TEST_CLAIMS", raising=False)
    assert TestClient(_app()).get("/who").status_code == 401
