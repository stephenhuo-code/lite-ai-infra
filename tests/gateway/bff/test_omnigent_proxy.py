# tests/gateway/bff/test_omnigent_proxy.py —— Task T4(9a):BFF 反代 omnigent + 身份注入 + 剥伪造头(TDD)
# 红线:
#  - 未认证 → 401(身份绝不到 omnigent)
#  - X-Forwarded-Email 只从【已认证会话】注入;客户端伪造的 X-Forwarded-Email 必须被剥离/覆盖
#  - managed 建会话 = JSON {agent_id, host_type:"managed"}(绝不 multipart,绝不 host_id)
#  - SSE:透传所有事件,不在 response.completed 处终止
import time

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from services.gateway.bff.middleware import install_bff
from services.gateway.app import build_gateway
from services.gateway.bff.session import SESSION_COOKIE, SessionCodec, SessionData

KEY = Fernet.generate_key()
AGENT_ID = "ag_58a1bc5bf0bba6d31ceeb7661f8d751c"


def _claims(_token):
    return {"sub": "u-alice", "organization": ["ent-demo"],
            "realm_access": {"roles": ["member"]},
            "preferred_username": "alice", "email": "alice@example.com"}


def _env(monkeypatch):
    monkeypatch.setenv("BFF_SESSION_KEY", KEY.decode())
    monkeypatch.setenv("OIDC_CLIENT_ID", "lite-ai-web")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "s")
    monkeypatch.setenv("OIDC_ISSUER", "http://kc/realms/x")
    monkeypatch.setenv("BFF_REDIRECT_URI", "http://gw/auth/callback")


def _valid_sd():
    return SessionData("at-alice", "rt", int(time.time()) + 300, csrf="csrf-xyz")


def _cookie(sd: SessionData) -> str:
    return SessionCodec(KEY).encode(sd)


class _Capture:
    """记录到 omnigent 的请求(MockTransport handler)。"""

    def __init__(self):
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/v1/agents":
            return httpx.Response(200, json={"data": [{"id": AGENT_ID, "name": "claude-native-ui"}]})
        if path == "/v1/sessions" and request.method == "GET":
            return httpx.Response(200, json={"data": []})
        if path == "/v1/sessions" and request.method == "POST":
            return httpx.Response(200, json={"id": "conv_123"})
        if path.endswith("/events"):
            return httpx.Response(202, json={"queued": True})
        if path.endswith("/items"):
            return httpx.Response(200, json={"data": []})
        return httpx.Response(404, json={"reason": "nf"})


def _app(monkeypatch, capture: _Capture, *, claims_fn=_claims):
    _env(monkeypatch)
    transport = httpx.MockTransport(capture.handler)
    app = build_gateway(routes={}, with_request_id=False)
    install_bff(app, refresh_fn=lambda rt: {}, claims_fn=claims_fn,
                omni_transport=transport, omni_base_url="http://omnigent:8000")
    return app


# ---- (a) 未认证 → 401,身份绝不到 omnigent ----

def test_unauthenticated_401_no_identity_to_omnigent(monkeypatch):
    cap = _Capture()
    c = TestClient(_app(monkeypatch, cap))
    r = c.get("/v1/ws/agents")
    assert r.status_code == 401
    assert cap.requests == []   # 完全没打到 omnigent


# ---- (b) 已认证:注入会话身份 + 剥离客户端伪造头 ----

def test_injects_session_email_and_strips_forged(monkeypatch):
    cap = _Capture()
    c = TestClient(_app(monkeypatch, cap))
    r = c.get("/v1/ws/agents", cookies={SESSION_COOKIE: _cookie(_valid_sd())},
              headers={"X-Forwarded-Email": "attacker@evil"})
    assert r.status_code == 200
    assert len(cap.requests) == 1
    sent = cap.requests[0].headers.get("x-forwarded-email")
    assert sent == "alice@example.com"        # 会话身份
    assert sent != "attacker@evil"            # 伪造头被剥离/覆盖


# ---- (c) managed 建会话 = JSON {agent_id, host_type:"managed"},非 multipart ----

def test_managed_create_is_json_not_multipart(monkeypatch):
    cap = _Capture()
    c = TestClient(_app(monkeypatch, cap))
    r = c.post("/v1/ws/sessions", cookies={SESSION_COOKIE: _cookie(_valid_sd())},
               headers={"X-CSRF-Token": "csrf-xyz"},
               json={"agent_id": AGENT_ID})
    assert r.status_code == 200
    assert r.json()["id"] == "conv_123"
    req = cap.requests[-1]
    assert req.method == "POST" and req.url.path == "/v1/sessions"
    ctype = req.headers.get("content-type", "")
    assert "application/json" in ctype
    assert "multipart" not in ctype
    import json as _json
    body = _json.loads(req.content)
    assert body == {"agent_id": AGENT_ID, "host_type": "managed"}
    assert "host_id" not in body
    assert req.headers.get("x-forwarded-email") == "alice@example.com"


def test_turn_posts_message_event(monkeypatch):
    cap = _Capture()
    c = TestClient(_app(monkeypatch, cap))
    r = c.post("/v1/ws/sessions/conv_123/turn", cookies={SESSION_COOKIE: _cookie(_valid_sd())},
               headers={"X-CSRF-Token": "csrf-xyz"}, json={"text": "hello"})
    assert r.status_code == 202
    req = cap.requests[-1]
    assert req.url.path == "/v1/sessions/conv_123/events"
    import json as _json
    body = _json.loads(req.content)
    assert body["type"] == "message"
    assert body["data"]["role"] == "user"
    assert body["data"]["content"][0]["text"] == "hello"
    assert req.headers.get("x-forwarded-email") == "alice@example.com"


# ---- (d) SSE 透传:所有事件穿透(含 response.completed 之后),并注入身份 ----

_SSE_BODY = (
    b"event: response.completed\ndata: {}\n\n"
    b"event: response.output_text.delta\ndata: {\"delta\":\"hi\"}\n\n"
    b"event: response.output_item.done\ndata: {}\n\n"
)


def test_sse_passthrough_all_events_and_injects_identity(monkeypatch):
    captured = {}

    async def _stream_body():
        # 模拟真实 SSE:分块 yield(MockTransport + AsyncClient.stream 需要 async 可迭代体)。
        yield _SSE_BODY[:40]
        yield _SSE_BODY[40:]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/sessions/conv_123/stream":
            captured["email"] = request.headers.get("x-forwarded-email")
            return httpx.Response(200, headers={"content-type": "text/event-stream"},
                                  content=_stream_body())
        return httpx.Response(404)

    _env(monkeypatch)
    transport = httpx.MockTransport(handler)
    app = build_gateway(routes={}, with_request_id=False)
    install_bff(app, refresh_fn=lambda rt: {}, claims_fn=_claims,
                omni_transport=transport, omni_base_url="http://omnigent:8000")

    c = TestClient(app)
    with c.stream("GET", "/v1/ws/sessions/conv_123/stream",
                  cookies={SESSION_COOKIE: _cookie(_valid_sd())}) as r:
        assert r.status_code == 200
        assert "text/event-stream" in r.headers.get("content-type", "")
        body = b"".join(r.iter_bytes())

    assert captured["email"] == "alice@example.com"   # 身份注入到 upstream
    # 全部事件穿透 —— 包括 response.completed 之后的 delta(不在 completed 处终止)
    assert b"response.completed" in body
    assert b"response.output_text.delta" in body
    assert b"response.output_item.done" in body
    assert body == _SSE_BODY
