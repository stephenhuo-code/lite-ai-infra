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


def _gw_with_state_bearer(transport, bearer: str | None):
    """装一个最小中间件设 request.state.bearer(模拟 BFF 会话注入),再挂反代。"""
    gw = make_service_app("gw", "0.1.0")

    @gw.middleware("http")
    async def _inject(request: Request, call_next):
        if bearer is not None:
            request.state.bearer = bearer
        return await call_next(request)

    mount_proxy(gw, prefix="/v1/me", base_url="http://down",
                client_factory=lambda: httpx.AsyncClient(transport=transport, base_url="http://down"))
    return gw


def test_proxy_injects_state_bearer_not_client_header():
    # C-1:bearer 来自 request.state.bearer(BFF 注入),客户端自带 Authorization 一律不转发。
    down = _downstream()
    transport = httpx.ASGITransport(app=down)
    gw = _gw_with_state_bearer(transport, bearer="session-tok")
    r = TestClient(gw).get("/v1/me/orgs", headers={"authorization": "Bearer forged"})
    assert r.status_code == 200
    assert r.json()["saw_auth"] == "Bearer session-tok"   # 注入的会话 bearer,非客户端 forged
    assert r.json()["path"] == "/v1/me/orgs"


def test_proxy_no_state_bearer_forwards_nothing():
    # C-1 红线:无 request.state.bearer 时,即便客户端带 Authorization 也绝不转发(下游收到空)。
    down = _downstream()
    transport = httpx.ASGITransport(app=down)
    gw = _gw_with_state_bearer(transport, bearer=None)
    r = TestClient(gw).get("/v1/me/orgs", headers={"authorization": "Bearer forged"})
    assert r.status_code == 200
    assert r.json()["saw_auth"] == ""                     # 绝不回退客户端原值
