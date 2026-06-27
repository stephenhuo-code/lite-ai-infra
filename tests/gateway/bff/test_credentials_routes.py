import tempfile
from pathlib import Path

from cryptography.fernet import Fernet
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from services.credential_vault.vault import CredentialVault
from services.gateway.bff.credentials_routes import make_credentials_router

_CLAIMS = {"sub": "u-alice", "organization": ["ent-demo"],
           "realm_access": {"roles": ["member"]}, "email": "alice@acme.test"}


def _app(tmp: Path):
    app = FastAPI()
    vault = CredentialVault(key=Fernet.generate_key().decode(), store_dir=tmp)

    @app.middleware("http")
    async def fake_session(request: Request, call_next):
        bearer = request.headers.get("x-test-bearer")
        request.state.bearer = bearer
        request.state.session = object() if bearer else None
        return await call_next(request)

    app.include_router(make_credentials_router(claims=lambda t: _CLAIMS, vault=vault))
    return app


def _client():
    tmp = Path(tempfile.mkdtemp())
    return TestClient(_app(tmp))


def test_unauthed_get_401():
    r = _client().get("/v1/me/model-credentials")
    assert r.status_code == 401


def test_authed_get_initial_status():
    r = _client().get("/v1/me/model-credentials", headers={"x-test-bearer": "tok"})
    assert r.status_code == 200
    assert r.json() == {"claude": False, "codex": False}


def test_put_then_get_status_and_no_secret_echo():
    c = _client()
    r = c.post("/v1/me/model-credentials", headers={"x-test-bearer": "tok"},
               json={"provider": "claude", "secret": "tok-x"})
    assert r.status_code == 200
    assert "tok-x" not in r.text                       # 安全红线:响应体不得含 secret 明文
    assert r.json() == {"ok": True}
    g = c.get("/v1/me/model-credentials", headers={"x-test-bearer": "tok"})
    assert g.json() == {"claude": True, "codex": False}


def test_delete_clears_provider():
    c = _client()
    c.post("/v1/me/model-credentials", headers={"x-test-bearer": "tok"},
           json={"provider": "claude", "secret": "tok-x"})
    d = c.delete("/v1/me/model-credentials/claude", headers={"x-test-bearer": "tok"})
    assert d.status_code == 200
    g = c.get("/v1/me/model-credentials", headers={"x-test-bearer": "tok"})
    assert g.json()["claude"] is False


def test_put_invalid_provider_400():
    c = _client()
    r = c.post("/v1/me/model-credentials", headers={"x-test-bearer": "tok"},
               json={"provider": "gpt", "secret": "tok-x"})
    assert r.status_code == 400
