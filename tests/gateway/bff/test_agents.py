# tests/gateway/bff/test_agents.py —— 智能体库(ADR-027):BFF admin 建 + 每企业隔离(TDD)
# 红线(负向):
#  - 非 enterprise-admin 建 → 403,且**不打到 omnigent**(can() 在反代前拦)
#  - admin 建:发往 omnigent /v1/agents 的 bundle 名带本企业前缀、只含安全字段、审计落一条
#  - 列表:只回内置(无前缀) + 本企业前缀(剥前缀);他企业的不可见
#  - 建会话:他企业 agent_id 被拒(无 managed 会话);内置/本企业 agent_id 放行(反代)
import io
import json
import tarfile
import time

import httpx
import pytest
import yaml
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from services.gateway.app import build_gateway
from services.gateway.bff.middleware import install_bff
from services.gateway.bff.session import SESSION_COOKIE, SessionCodec, SessionData

KEY = Fernet.generate_key()

# omnigent agent name 企业前缀分隔符 = ASCII 下划线("_")。
# 实测 omnigent name 必须匹配 ^[a-zA-Z0-9_-]+$(无控制符/无非 ASCII),旧 U+001F 会被 400 拒;
# 故 BFF:name = "<alias>_<ascii-slug>" 承载企业归属,人类展示名(可含中文)落 description 首行。
# KC org alias(ent-aaa)与 omnigent 内置名(*-native-ui 等)均不含 "_" → 归属不可伪造、内置不误判。
SEP = "_"

ENTA = "ent-aaa"
ENTB = "ent-bbb"

BUILTIN_ID = "ag_builtin_x"
AGENTA_ID = "ag_enta_1"
AGENTB_ID = "ag_entb_1"

# 企业 agent:name 是 "<alias>_<slug>"(无人类展示名),展示名落 description 首行。
AGENTA_NAME = f"{ENTA}{SEP}kefu-aa11bb"
AGENTB_NAME = f"{ENTB}{SEP}coder-cc22dd"
AGENTA_DISPLAY = "客服助手"
AGENTB_DISPLAY = "代码助手"


def _env(monkeypatch):
    monkeypatch.setenv("BFF_SESSION_KEY", KEY.decode())
    monkeypatch.setenv("OIDC_CLIENT_ID", "lite-ai-web")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "s")
    monkeypatch.setenv("OIDC_ISSUER", "http://kc/realms/x")
    monkeypatch.setenv("BFF_REDIRECT_URI", "http://gw/auth/callback")


def _claims_for(*, sub, org, roles):
    def _fn(_token):
        return {"sub": sub, "organization": [org],
                "realm_access": {"roles": list(roles)},
                "preferred_username": sub, "email": f"{sub}@example.com"}
    return _fn


# 角色固件:enterprise-admin / member,绑某企业
ADMIN_A = _claims_for(sub="alice", org=ENTA, roles=["enterprise-admin"])
MEMBER_A = _claims_for(sub="bob", org=ENTA, roles=["member"])
MEMBER_B = _claims_for(sub="carol", org=ENTB, roles=["member"])
ADMIN_B = _claims_for(sub="dave", org=ENTB, roles=["enterprise-admin"])


def _valid_sd():
    return SessionData("at", "rt", int(time.time()) + 300, csrf="csrf-xyz")


def _cookie(sd: SessionData) -> str:
    return SessionCodec(KEY).encode(sd)


class _FakeSink:
    """记录审计写入(AuditSink.put)。"""

    def __init__(self):
        self.events: list[dict] = []

    def put(self, key: str, body: bytes) -> None:
        self.events.append(json.loads(body.decode()))


class _Capture:
    """MockTransport handler:记录到 omnigent 的请求 + 可配置 /v1/agents 列表。"""

    def __init__(self, *, agents=None):
        self.requests: list[httpx.Request] = []
        # omnigent GET /v1/agents 返回的全量(含他企业,模拟 omnigent 租户无关)
        self._agents = agents if agents is not None else [
            {"id": BUILTIN_ID, "name": "claude-native-ui", "harness": "claude-native",
             "description": "Built-in Claude template"},
            # 企业 agent:name=<alias>_<slug>(无中文),展示名在 description 首行(omnigent 原样存)。
            {"id": AGENTA_ID, "name": AGENTA_NAME, "harness": "claude-native",
             "description": f"{AGENTA_DISPLAY}\n\nentA 的客服"},
            {"id": AGENTB_ID, "name": AGENTB_NAME, "harness": "claude-native",
             "description": f"{AGENTB_DISPLAY}\n\nentB 的代码助手"},
        ]

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/v1/agents" and request.method == "GET":
            return httpx.Response(200, json={"data": self._agents})
        if path == "/v1/agents" and request.method == "POST":
            # 回 AgentObject(含 id);name 回显上传名(omnigent 原样存)
            return httpx.Response(200, json={"id": "ag_new_1", "name": "created",
                                             "harness": "claude-native", "description": ""})
        if path == "/v1/sessions" and request.method == "POST":
            return httpx.Response(200, json={"id": "conv_123"})
        return httpx.Response(404, json={"reason": "nf"})


def _app(monkeypatch, capture: _Capture, *, claims_fn, sink=None):
    _env(monkeypatch)
    transport = httpx.MockTransport(capture.handler)
    app = build_gateway(routes={}, with_request_id=False)
    from libs.audit.oss_audit import AuditWriter
    audit = AuditWriter(sink) if sink is not None else None
    install_bff(app, refresh_fn=lambda rt: {}, claims_fn=claims_fn,
                omni_transport=transport, omni_base_url="http://omnigent:8000",
                audit_writer=audit)
    return app


def _unpack_bundle(req: httpx.Request) -> dict:
    """从 multipart POST /v1/agents 取出 bundle 里的 config.yaml(解析为 dict)。"""
    # multipart:解析出 file field "bundle" 的字节
    ctype = req.headers.get("content-type", "")
    assert "multipart/form-data" in ctype, ctype
    boundary = ctype.split("boundary=")[1].encode()
    parts = req.content.split(b"--" + boundary)
    blob = None
    for p in parts:
        if b'name="bundle"' in p:
            blob = p.split(b"\r\n\r\n", 1)[1].rsplit(b"\r\n", 1)[0]
            break
    assert blob is not None, "no bundle field"
    tf = tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz")
    member = next(m for m in tf.getmembers() if m.name.endswith("config.yaml"))
    return yaml.safe_load(tf.extractfile(member).read())


# ===== (1) 非 admin 建 → 403,且不打到 omnigent =====

def test_non_admin_create_403_no_omnigent(monkeypatch):
    cap = _Capture()
    c = TestClient(_app(monkeypatch, cap, claims_fn=MEMBER_A))
    r = c.post("/v1/ws/agents", cookies={SESSION_COOKIE: _cookie(_valid_sd())},
               headers={"X-CSRF-Token": "csrf-xyz"}, json={"name": "客服助手"})
    assert r.status_code == 403
    assert r.json().get("reason")
    # can() 在反代前拦 → 完全没打到 omnigent(无任何请求)
    assert cap.requests == []


# ===== (2) admin 建:bundle 名带本企业前缀 + 只含安全字段 + 审计落一条 =====

def test_admin_create_prefixed_safe_bundle_and_audit(monkeypatch):
    cap = _Capture()
    sink = _FakeSink()
    c = TestClient(_app(monkeypatch, cap, claims_fn=ADMIN_A, sink=sink))
    r = c.post("/v1/ws/agents", cookies={SESSION_COOKIE: _cookie(_valid_sd())},
               headers={"X-CSRF-Token": "csrf-xyz"},
               json={"name": "客服助手", "instructions": "你是客服", "model": "claude-x"})
    assert r.status_code == 200, r.text
    # 打到 omnigent 的是 POST /v1/agents(multipart)
    posts = [q for q in cap.requests if q.url.path == "/v1/agents" and q.method == "POST"]
    assert len(posts) == 1
    cfg = _unpack_bundle(posts[0])
    # name 带【会话企业】前缀(不可伪造,客户端从没发过前缀)+ 是合法 omnigent 标识(^[a-zA-Z0-9_-]+$)。
    import re
    assert cfg["name"].partition(SEP)[0] == ENTA          # 前缀 == 会话企业
    assert re.fullmatch(r"[a-zA-Z0-9_-]+", cfg["name"])    # omnigent name 校验:无控制符/非 ASCII
    # 人类展示名(中文)进不了 name → 落 description 首行(omnigent 原样 round-trip)。
    assert cfg["description"].split("\n", 1)[0] == "客服助手"
    # 只含安全字段
    assert cfg["instructions"] == "你是客服"
    assert cfg["executor"]["type"] == "omnigent"
    assert cfg["executor"]["config"]["harness"] == "claude-native"
    assert cfg["llm"]["model"] == "claude-x"
    # 绝不含不安全字段
    for bad in ("mcp_servers", "tools", "skills", "spawn", "timers"):
        assert bad not in cfg
    assert "auth" not in cfg["executor"]
    # 身份注入
    assert posts[0].headers.get("x-forwarded-email") == "alice@example.com"
    # 审计落一条 create / allow
    assert len(sink.events) == 1
    ev = sink.events[0]
    assert ev["action"] == "agent:create"
    assert ev["decision"] == "allow"
    assert ev["enterprise_id"] == ENTA
    assert ev["actor_user"] == "alice"
    # 前端拿到的展示名是干净人类名(无企业前缀/无内部 slug),且不泄露内部 omnigent name。
    assert r.json()["name"] == "客服助手"
    assert SEP not in r.json()["name"]


def test_admin_create_default_harness(monkeypatch):
    cap = _Capture()
    c = TestClient(_app(monkeypatch, cap, claims_fn=ADMIN_A))
    r = c.post("/v1/ws/agents", cookies={SESSION_COOKIE: _cookie(_valid_sd())},
               headers={"X-CSRF-Token": "csrf-xyz"}, json={"name": "助手"})
    assert r.status_code == 200, r.text
    posts = [q for q in cap.requests if q.url.path == "/v1/agents" and q.method == "POST"]
    cfg = _unpack_bundle(posts[0])
    assert cfg["executor"]["config"]["harness"] == "claude-native"  # 默认
    # 留空模型 → 不写 llm.model(用模板默认)
    assert "llm" not in cfg or not cfg.get("llm", {}).get("model")


def test_create_name_required(monkeypatch):
    cap = _Capture()
    c = TestClient(_app(monkeypatch, cap, claims_fn=ADMIN_A))
    r = c.post("/v1/ws/agents", cookies={SESSION_COOKIE: _cookie(_valid_sd())},
               headers={"X-CSRF-Token": "csrf-xyz"}, json={"name": "   "})
    assert r.status_code == 400
    assert cap.requests == []


def test_create_rejects_client_supplied_sep_prefix_forgery(monkeypatch):
    # 客户端在 name 里塞分隔符(U+001F)试图伪造企业前缀 → BFF 400,绝不打到 omnigent。
    # (前缀只能由 BFF 据已认证会话 alias 写入;客户端供 SEP = 越界伪造,直接拒。)
    cap = _Capture()
    sink = _FakeSink()
    c = TestClient(_app(monkeypatch, cap, claims_fn=ADMIN_A, sink=sink))  # 用 admin:过了 can() 门也仍拒
    r = c.post("/v1/ws/agents", cookies={SESSION_COOKIE: _cookie(_valid_sd())},
               headers={"X-CSRF-Token": "csrf-xyz"},
               json={"name": f"{ENTB}{SEP}伪造助手"})  # 伪造他企业前缀
    assert r.status_code == 400, r.text
    # 没建任何 agent / 没打到 omnigent(SEP 门在反代前拦),也不落审计
    assert cap.requests == []
    assert sink.events == []


# ===== (2b) 红线 §1:alias 含 "_" 与 "_"-分隔归属方案不兼容 → fail-loud 拒(create + list) =====

# alias "ent_foo" 含 "_" → partition("_")[0] 会截成 "ent",可能让 "ent" 误见到 "ent_foo" 的 agent
# (跨企业泄漏)→ BFF 必须 fail-loud 拒,绝不静默错隔离。
ADMIN_BAD = _claims_for(sub="eve", org="ent_foo", roles=["enterprise-admin"])
MEMBER_BAD = _claims_for(sub="frank", org="ent_foo", roles=["member"])


def test_create_rejects_alias_with_underscore(monkeypatch):
    cap = _Capture()
    sink = _FakeSink()
    c = TestClient(_app(monkeypatch, cap, claims_fn=ADMIN_BAD, sink=sink))
    r = c.post("/v1/ws/agents", cookies={SESSION_COOKIE: _cookie(_valid_sd())},
               headers={"X-CSRF-Token": "csrf-xyz"}, json={"name": "助手"})
    assert r.status_code == 409, r.text
    assert r.json()["reason"] == "enterprise alias incompatible with agent library"
    # 绝不打到 omnigent(guard 在反代前拦),也不落审计、不建任何 agent
    assert cap.requests == []
    assert sink.events == []


def test_list_rejects_alias_with_underscore(monkeypatch):
    cap = _Capture()
    c = TestClient(_app(monkeypatch, cap, claims_fn=MEMBER_BAD))
    r = c.get("/v1/ws/agents", cookies={SESSION_COOKIE: _cookie(_valid_sd())})
    assert r.status_code == 409, r.text
    assert r.json()["reason"] == "enterprise alias incompatible with agent library"
    # 绝不拉 omnigent 全量(否则按错前缀过滤 = 可能跨企业泄漏)
    assert cap.requests == []


# ===== (3) 列表过滤:内置 + 本企业(剥前缀);他企业不可见 =====

def test_list_filters_per_enterprise_and_strips_prefix(monkeypatch):
    cap = _Capture()
    c = TestClient(_app(monkeypatch, cap, claims_fn=MEMBER_A))  # entA 成员
    r = c.get("/v1/ws/agents", cookies={SESSION_COOKIE: _cookie(_valid_sd())})
    assert r.status_code == 200
    data = r.json()["data"]
    by_id = {a["id"]: a for a in data}
    # 内置(无前缀)+ 本企业 agent 可见;他企业(entB)不可见
    assert BUILTIN_ID in by_id
    assert AGENTA_ID in by_id
    assert AGENTB_ID not in by_id
    # 展示名干净(从 description 首行还原),无内部 slug/无 SEP;用户描述拆出(空行后那段)
    assert by_id[AGENTA_ID]["name"] == "客服助手"
    assert SEP not in by_id[AGENTA_ID]["name"]
    assert by_id[AGENTA_ID]["description"] == "entA 的客服"
    # builtin / enterprise_owned 标志供 UI
    assert by_id[BUILTIN_ID]["builtin"] is True
    assert by_id[BUILTIN_ID]["enterprise_owned"] is False
    assert by_id[AGENTA_ID]["builtin"] is False
    assert by_id[AGENTA_ID]["enterprise_owned"] is True


def test_list_builtin_visible_to_other_enterprise(monkeypatch):
    cap = _Capture()
    c = TestClient(_app(monkeypatch, cap, claims_fn=MEMBER_B))  # entB 成员
    r = c.get("/v1/ws/agents", cookies={SESSION_COOKIE: _cookie(_valid_sd())})
    data = r.json()["data"]
    by_id = {a["id"]: a for a in data}
    assert BUILTIN_ID in by_id          # 内置全局共享
    assert AGENTB_ID in by_id           # 自己的
    assert AGENTA_ID not in by_id        # 别人的不可见


# ===== (4) 建会话隔离:他企业 agent_id 被拒;内置/本企业放行 =====

def test_session_create_rejects_other_enterprise_agent(monkeypatch):
    cap = _Capture()
    c = TestClient(_app(monkeypatch, cap, claims_fn=MEMBER_A))  # entA
    r = c.post("/v1/ws/sessions", cookies={SESSION_COOKIE: _cookie(_valid_sd())},
               headers={"X-CSRF-Token": "csrf-xyz"}, json={"agent_id": AGENTB_ID})  # entB 的
    assert r.status_code in (403, 404)
    # 绝不创建 managed 会话(无 POST /v1/sessions 到 omnigent)
    assert not any(q.url.path == "/v1/sessions" and q.method == "POST" for q in cap.requests)


def test_session_create_allows_own_agent(monkeypatch):
    cap = _Capture()
    c = TestClient(_app(monkeypatch, cap, claims_fn=MEMBER_A))  # entA
    r = c.post("/v1/ws/sessions", cookies={SESSION_COOKIE: _cookie(_valid_sd())},
               headers={"X-CSRF-Token": "csrf-xyz"}, json={"agent_id": AGENTA_ID})
    assert r.status_code == 200
    posts = [q for q in cap.requests if q.url.path == "/v1/sessions" and q.method == "POST"]
    assert len(posts) == 1
    body = json.loads(posts[0].content)
    assert body == {"agent_id": AGENTA_ID, "host_type": "managed"}


def test_session_create_allows_builtin_agent(monkeypatch):
    cap = _Capture()
    c = TestClient(_app(monkeypatch, cap, claims_fn=MEMBER_A))
    r = c.post("/v1/ws/sessions", cookies={SESSION_COOKIE: _cookie(_valid_sd())},
               headers={"X-CSRF-Token": "csrf-xyz"}, json={"agent_id": BUILTIN_ID})
    assert r.status_code == 200
    assert any(q.url.path == "/v1/sessions" and q.method == "POST" for q in cap.requests)


def test_session_create_rejects_unknown_agent(monkeypatch):
    cap = _Capture()
    c = TestClient(_app(monkeypatch, cap, claims_fn=MEMBER_A))
    r = c.post("/v1/ws/sessions", cookies={SESSION_COOKIE: _cookie(_valid_sd())},
               headers={"X-CSRF-Token": "csrf-xyz"}, json={"agent_id": "ag_does_not_exist"})
    assert r.status_code in (403, 404)
    assert not any(q.url.path == "/v1/sessions" and q.method == "POST" for q in cap.requests)
