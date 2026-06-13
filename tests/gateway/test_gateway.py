# tests/gateway/test_gateway.py
import httpx
from fastapi.testclient import TestClient
from services._scaffold.app import make_service_app
from services.gateway.app import build_gateway


def _identity_stub():
    app = make_service_app("identity-stub", "0.1.0")
    @app.get("/v1/me/orgs")
    def me():
        return {"user": "u-proxied", "is_platform_admin": False, "memberships": []}
    return app


def _gw():
    stub = _identity_stub()
    transport = httpx.ASGITransport(app=stub)
    return build_gateway(routes={
        "/v1/me": ("http://identity", lambda: httpx.AsyncClient(transport=transport, base_url="http://identity")),
    })


def test_gateway_proxies_identity_route():
    r = TestClient(_gw()).get("/v1/me/orgs")
    assert r.status_code == 200 and r.json()["user"] == "u-proxied"


def test_gateway_healthz():
    assert TestClient(_gw()).get("/healthz").json() == {"status": "ok"}


def test_gateway_unknown_route_404():
    assert TestClient(_gw()).get("/v1/nope").status_code == 404
