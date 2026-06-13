# tests/scaffold/test_proxy.py
import httpx
from fastapi import Request
from fastapi.testclient import TestClient
from services._scaffold.app import make_service_app
from services._scaffold.proxy import mount_proxy


def _downstream():
    app = make_service_app("stub", "0.1.0")
    @app.get("/v1/me/orgs")
    def echo(request: Request):
        return {"saw_auth": request.headers.get("authorization", ""), "path": "/v1/me/orgs"}
    return app


def test_proxy_forwards_path_and_bearer():
    down = _downstream()
    transport = httpx.ASGITransport(app=down)
    gw = make_service_app("gw", "0.1.0")
    mount_proxy(gw, prefix="/v1/me", base_url="http://down",
                client_factory=lambda: httpx.AsyncClient(transport=transport, base_url="http://down"))
    r = TestClient(gw).get("/v1/me/orgs", headers={"authorization": "Bearer tok-1"})
    assert r.status_code == 200
    assert r.json()["saw_auth"] == "Bearer tok-1"
    assert r.json()["path"] == "/v1/me/orgs"
