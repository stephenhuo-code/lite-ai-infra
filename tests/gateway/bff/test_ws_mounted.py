# plan 9 gap①:install_bff 应挂 /v1/ws/* 路由(否则前端调 /v1/ws/sessions → 404)。
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.gateway.bff.middleware import install_bff

KEY = Fernet.generate_key()


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("BFF_SESSION_KEY", KEY.decode())
    monkeypatch.setenv("OIDC_CLIENT_ID", "lite-ai-web")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "s")
    monkeypatch.setenv("OIDC_ISSUER", "http://kc/realms/x")
    monkeypatch.setenv("BFF_REDIRECT_URI", "http://localhost/cb")


def _app():
    app = FastAPI()
    install_bff(app, claims_fn=lambda t: {"sub": "u"})
    return app


def test_ws_sessions_route_mounted_401_not_404():
    r = TestClient(_app()).post("/v1/ws/sessions")     # 无会话 → 路由内 401(已挂);未挂则 404
    assert r.status_code == 401


def test_ws_turn_route_mounted():
    r = TestClient(_app()).post("/v1/ws/sessions/s1/turn", json={"text": "hi"})
    assert r.status_code == 401
