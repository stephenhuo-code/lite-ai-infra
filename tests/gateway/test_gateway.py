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


def _collection_stub():
    """下游服务在反代前缀处恰有一个集合端点(如 metadata 的 /v1/catalogs)。"""
    app = make_service_app("metadata-stub", "0.1.0")

    @app.get("/v1/catalogs")
    def catalogs():
        return {"names": ["data"]}

    @app.get("/v1/catalogs/{catalog}/schemas")
    def schemas(catalog: str):
        return {"names": ["datasets"], "catalog": catalog}

    return app


def _gw_collection():
    stub = _collection_stub()
    transport = httpx.ASGITransport(app=stub)
    return build_gateway(routes={
        "/v1/catalogs": ("http://meta", lambda: httpx.AsyncClient(transport=transport, base_url="http://meta")),
    })


def test_gateway_proxies_bare_prefix_collection():
    # 反代前缀处的集合端点(无子路径)必须可达,不能 307/404
    r = TestClient(_gw_collection()).get("/v1/catalogs")
    assert r.status_code == 200 and r.json()["names"] == ["data"]


def test_gateway_proxies_subpath_under_prefix():
    r = TestClient(_gw_collection()).get("/v1/catalogs/data/schemas")
    assert r.status_code == 200 and r.json()["names"] == ["datasets"]
