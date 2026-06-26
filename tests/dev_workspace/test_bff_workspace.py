import json

import httpx

from services.gateway.bff.omnigent_client import OmnigentClient
from services.gateway.bff.workspace import (
    create_workspace_session,
    strip_forged_identity_headers,
)
from services.gateway.bff.wstoken import WorkspaceTokenStore


def _client(handler):
    return OmnigentClient(base_url="http://omnigent:8000", email="alice@acme.test",
                          transport=httpx.MockTransport(handler))


def test_create_session_sends_header_auth_and_agent_id():
    seen = {}

    def h(req):
        seen["email"] = req.headers.get("X-Forwarded-Email")
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"id": "sess-omni-1"})

    sid = _client(h).create_session(agent_id="liteai_devws")
    assert sid == "sess-omni-1"
    assert seen["email"] == "alice@acme.test"      # header-auth 注入
    assert seen["body"]["agent_id"] == "liteai_devws"   # Task0:agent_id 必填


def test_register_mcp_sends_tokenized_url():
    seen = {}

    def h(req):
        if req.url.path.endswith("/mcp-servers"):
            seen["body"] = json.loads(req.content)
        return httpx.Response(201, json={})

    _client(h).register_mcp(session_id="sess-omni-1", name="liteai",
                            url="http://liteai-mcp:8000/s/tok-xyz/mcp")
    assert seen["body"]["transport"] == "http"
    assert seen["body"]["url"].endswith("/s/tok-xyz/mcp")


def test_strip_forged_identity_header():
    out = strip_forged_identity_headers({"X-Forwarded-Email": "evil@x", "Cookie": "ok"})
    assert "X-Forwarded-Email" not in out and "Cookie" in out


def test_create_workspace_session_binds_token_to_caller():
    calls = {}

    def h(req):
        if req.url.path.endswith("/mcp-servers"):
            calls["url"] = json.loads(req.content)["url"]
            return httpx.Response(201, json={})
        return httpx.Response(200, json={"id": "sess-7"})

    store = WorkspaceTokenStore(now=lambda: 0)
    omni = OmnigentClient("http://omnigent:8000", email="alice@acme.test",
                          transport=httpx.MockTransport(h))
    out = create_workspace_session(sub="u-alice", enterprise="ent-demo", role="member",
                                   agent_id="liteai_devws", store=store, omni=omni,
                                   mcp_base_url="http://liteai-mcp:8000")
    assert out["session_id"] == "sess-7"
    tok = calls["url"].rsplit("/", 2)[1]          # /s/<tok>/mcp
    r = store.resolve(tok)
    assert r.sub == "u-alice" and r.enterprise == "ent-demo" and r.session == "sess-7"
