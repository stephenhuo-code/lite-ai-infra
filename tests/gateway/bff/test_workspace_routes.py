import httpx
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from services.gateway.bff.omnigent_client import OmnigentClient
from services.gateway.bff.workspace_routes import make_workspace_router
from services.gateway.bff.wstoken import WorkspaceTokenStore

_CLAIMS = {"sub": "u-alice", "organization": ["ent-demo"],
           "realm_access": {"roles": ["member"]}, "email": "alice@acme.test"}


def _omni_factory(email):
    def h(req):
        if req.url.path.endswith("/mcp-servers"):
            return httpx.Response(201, json={})
        assert req.headers.get("X-Forwarded-Email") == "alice@acme.test"   # header-auth
        return httpx.Response(200, json={"id": "sess-omni"})
    return OmnigentClient("http://omnigent:8000", email=email, transport=httpx.MockTransport(h))


def _app():
    app = FastAPI()

    @app.middleware("http")
    async def fake_session(request: Request, call_next):
        bearer = request.headers.get("x-test-bearer")
        request.state.bearer = bearer
        request.state.session = object() if bearer else None
        return await call_next(request)

    app.include_router(make_workspace_router(
        claims=lambda t: _CLAIMS, store=WorkspaceTokenStore(now=lambda: 0),
        omni_factory=_omni_factory, mcp_base_url="http://mcp:8000"))
    return app


def test_authed_creates_session():
    r = TestClient(_app()).post("/v1/ws/sessions", headers={"x-test-bearer": "tok"})
    assert r.status_code == 200 and r.json()["session_id"] == "sess-omni"


def test_unauthed_401():
    r = TestClient(_app()).post("/v1/ws/sessions")
    assert r.status_code == 401


def test_turn_posts_user_message():
    seen = {}

    def h(req):
        if req.url.path.endswith("/events"):
            import json as _j
            seen["body"] = _j.loads(req.content)
            return httpx.Response(200, json={"queued": True})
        return httpx.Response(200, json={"id": "x"})

    def omni_factory(email):
        return OmnigentClient("http://omnigent:8000", email=email, transport=httpx.MockTransport(h))

    app = FastAPI()

    @app.middleware("http")
    async def fake(request: Request, call_next):
        b = request.headers.get("x-test-bearer")
        request.state.bearer = b
        request.state.session = object() if b else None
        return await call_next(request)

    app.include_router(make_workspace_router(
        claims=lambda t: _CLAIMS, store=WorkspaceTokenStore(now=lambda: 0),
        omni_factory=omni_factory, mcp_base_url="http://mcp:8000"))
    r = TestClient(app).post("/v1/ws/sessions/s1/turn", headers={"x-test-bearer": "tok"},
                             json={"text": "探查 coco"})
    assert r.status_code == 200 and r.json()["queued"] is True
    assert seen["body"]["data"]["content"][0]["text"] == "探查 coco"
