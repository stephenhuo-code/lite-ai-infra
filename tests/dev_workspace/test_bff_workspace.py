import json

import httpx

from services.gateway.bff.omnigent_client import OmnigentClient
from services.gateway.bff.workspace import (
    create_workspace_session,
    strip_forged_identity_headers,
)
from services.gateway.bff.wstoken import TokenClaims, WorkspaceTokenStore


def _client(handler):
    return OmnigentClient(base_url="http://omnigent:8000", email="alice@acme.test",
                          transport=httpx.MockTransport(handler))


def test_create_session_bundled_upload():
    seen = {}

    def h(req):
        seen["email"] = req.headers.get("X-Forwarded-Email")
        seen["ctype"] = req.headers.get("content-type", "")
        seen["body"] = req.content
        return httpx.Response(200, json={"session_id": "sess-omni-1"})

    sid = _client(h).create_session(agent_config_yaml="name: liteai_devws\n")
    assert sid == "sess-omni-1"
    assert seen["email"] == "alice@acme.test"          # header-auth 注入
    assert "multipart/form-data" in seen["ctype"]      # bundled multipart
    assert b"bundle" in seen["body"] and b"metadata" in seen["body"]


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
        if req.url.path == "/v1/hosts":
            return httpx.Response(200, json={"hosts": [{"host_id": "h1", "status": "online"}]})
        if req.url.path.endswith("/runners"):
            return httpx.Response(200, json={"runner_id": "r1"})
        return httpx.Response(200, json={"session_id": "sess-7"})

    store = WorkspaceTokenStore(now=lambda: 0)
    omni = OmnigentClient("http://omnigent:8000", email="alice@acme.test",
                          transport=httpx.MockTransport(h))
    out = create_workspace_session(sub="u-alice", enterprise="ent-demo", role="member",
                                   agent_config_yaml="name: liteai_devws\n", store=store, omni=omni,
                                   mcp_base_url="http://liteai-mcp:8000")
    assert out["session_id"] == "sess-7"
    tok = calls["url"].rsplit("/", 2)[1]          # /s/<tok>/mcp
    r = store.resolve(tok)
    assert r.sub == "u-alice" and r.enterprise == "ent-demo" and r.session == "sess-7"


from services.gateway.bff.workspace import close_workspace_session
from services.gateway.bff.workspace_store import workspace_prefix as _wp


class _FakeOSS:
    def __init__(self, objs=None):
        self.objs = dict(objs or {})

    def list(self, prefix):
        return [k for k in self.objs if k.startswith(prefix)]

    def get(self, k):
        return self.objs[k]

    def put_object(self, k, b):
        self.objs[k] = b


class _FakeFS:
    def __init__(self):
        self.files = {}

    def write(self, rel, b):
        self.files[rel] = b

    def read(self, rel):
        return self.files[rel]

    def listrel(self):
        return list(self.files)


def test_create_with_ws_hydrates_workspace():
    pfx = _wp(enterprise="ent-demo", owner="u-alice", ws="w1")
    oss = _FakeOSS({pfx + "recipe.py": b"x"})
    fs = _FakeFS()

    def h(req):
        if req.url.path.endswith("/mcp-servers"):
            return httpx.Response(201, json={})
        if req.url.path == "/v1/hosts":
            return httpx.Response(200, json={"hosts": [{"host_id": "h1", "status": "online"}]})
        if req.url.path.endswith("/runners"):
            return httpx.Response(200, json={"runner_id": "r1"})
        return httpx.Response(200, json={"session_id": "sess-h"})

    store = WorkspaceTokenStore(now=lambda: 0)
    omni = OmnigentClient("http://omnigent:8000", email="a@x", transport=httpx.MockTransport(h))
    create_workspace_session(sub="u-alice", enterprise="ent-demo", role="member",
                             agent_config_yaml="name: liteai_devws\n", store=store, omni=omni,
                             mcp_base_url="http://mcp:8000", ws="w1", oss=oss, fs=fs)
    assert fs.files["recipe.py"] == b"x"          # 水合到工作目录


def test_close_persists_and_revokes():
    store = WorkspaceTokenStore(now=lambda: 0)
    tok = store.mint(TokenClaims("u-alice", "ent-demo", "member", "sess-c"))
    oss = _FakeOSS()
    fs = _FakeFS()
    fs.write("out.txt", b"y")
    out = close_workspace_session(session="sess-c", enterprise="ent-demo", owner="u-alice",
                                  ws="w1", store=store, oss=oss, fs=fs)
    assert out["persisted"] == 1 and out["revoked"] == 1
    assert store.resolve(tok) is None              # 令牌已撤销
    assert any(k.endswith("workspace/w1/out.txt") for k in oss.objs)   # 持久化回 OSS
