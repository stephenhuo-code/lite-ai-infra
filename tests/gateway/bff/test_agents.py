# tests/gateway/bff/test_agents.py —— 智能体库(ADR-027):BFF admin 建 + 每企业隔离(TDD)
# 红线(负向):
#  - 非 enterprise-admin 建 → 403,且**不打到 omnigent**(can() 在反代前拦)
#  - admin 建:发往 omnigent /v1/agents 的 bundle 名带本企业前缀、只含安全字段、审计落一条
#  - 列表:只回本企业前缀(剥前缀);内置和他企业的不可见
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
            cfg = _unpack_bundle(request)
            new = {
                "id": f"ag_new_{len(self._agents)}",
                "name": cfg["name"],
                "harness": cfg["executor"]["config"]["harness"],
                "description": cfg.get("description", ""),
            }
            self._agents.append(new)
            return httpx.Response(200, json=new)
        if path == "/v1/sessions" and request.method == "POST":
            return httpx.Response(200, json={"id": "conv_123"})
        if path.startswith("/v1/agents/") and request.method == "DELETE":
            return httpx.Response(200, json={"deleted": True,
                                             "id": path.rsplit("/", 1)[-1]})
        return httpx.Response(404, json={"reason": "nf"})


def _bundle_posts(cap: _Capture) -> list[httpx.Request]:
    return [q for q in cap.requests if q.url.path == "/v1/agents" and q.method == "POST"]


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


def test_default_enterprise_agent_templates_are_fixed_four():
    from services.gateway.bff import omnigent_proxy as op

    names = [t.display_name for t in op.DEFAULT_ENTERPRISE_AGENTS]

    assert names == ["minimax", "debby", "codex", "polly"]
    by_name = {t.display_name: t for t in op.DEFAULT_ENTERPRISE_AGENTS}
    assert by_name["minimax"].harness == "openai-agents"
    assert by_name["minimax"].model == "MiniMax-Text-01"
    assert by_name["debby"].harness == "claude-sdk"
    assert by_name["codex"].harness == "codex"
    assert by_name["polly"].harness == "claude-sdk"
    assert all(t.instructions.strip() for t in op.DEFAULT_ENTERPRISE_AGENTS)


def test_ensure_default_agents_creates_missing_four_for_enterprise():
    from services.gateway.bff.omnigent_proxy import ensure_default_agents_for_enterprise

    cap = _Capture(agents=[])
    result = ensure_default_agents_for_enterprise(
        ENTA,
        omni_base_url="http://omnigent:8000",
        identity_email="system@lite-ai.local",
        transport=httpx.MockTransport(cap.handler),
    )

    assert result.created == ["minimax", "debby", "codex", "polly"]
    assert result.skipped == []
    posts = _bundle_posts(cap)
    assert len(posts) == 4
    created_cfgs = [_unpack_bundle(p) for p in posts]
    assert [c["description"].split("\n", 1)[0] for c in created_cfgs] == [
        "minimax", "debby", "codex", "polly"]
    assert all(c["name"].startswith(f"{ENTA}{SEP}") for c in created_cfgs)
    assert "auth" not in created_cfgs[0]["executor"]


def test_ensure_default_agents_is_idempotent():
    from services.gateway.bff.omnigent_proxy import ensure_default_agents_for_enterprise

    cap = _Capture(agents=[])
    transport = httpx.MockTransport(cap.handler)

    first = ensure_default_agents_for_enterprise(
        ENTA, omni_base_url="http://omnigent:8000",
        identity_email="system@lite-ai.local", transport=transport)
    second = ensure_default_agents_for_enterprise(
        ENTA, omni_base_url="http://omnigent:8000",
        identity_email="system@lite-ai.local", transport=transport)

    assert first.created == ["minimax", "debby", "codex", "polly"]
    assert second.created == []
    assert second.skipped == ["minimax", "debby", "codex", "polly"]
    assert len(_bundle_posts(cap)) == 4


def test_ensure_default_agents_backfills_only_missing_defaults():
    from services.gateway.bff.omnigent_proxy import ensure_default_agents_for_enterprise

    cap = _Capture(agents=[
        {"id": AGENTA_ID, "name": AGENTA_NAME, "harness": "claude-sdk",
         "description": "debby\n\n管理员已改过的 debby"},
    ])

    result = ensure_default_agents_for_enterprise(
        ENTA,
        omni_base_url="http://omnigent:8000",
        identity_email="system@lite-ai.local",
        transport=httpx.MockTransport(cap.handler),
    )

    assert result.created == ["minimax", "codex", "polly"]
    assert result.skipped == ["debby"]
    assert len(_bundle_posts(cap)) == 3


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


# ===== (3) 列表过滤:本企业(剥前缀);内置/他企业不可见 =====

def test_list_filters_per_enterprise_and_strips_prefix(monkeypatch):
    cap = _Capture()
    c = TestClient(_app(monkeypatch, cap, claims_fn=MEMBER_A))  # entA 成员
    r = c.get("/v1/ws/agents", cookies={SESSION_COOKIE: _cookie(_valid_sd())})
    assert r.status_code == 200
    data = r.json()["data"]
    names = [a["name"] for a in data]
    assert names == [AGENTA_DISPLAY]
    # 展示名干净(从 description 首行还原),无内部 slug/无 SEP;用户描述拆出(空行后那段)
    assert data[0]["name"] == AGENTA_DISPLAY
    assert SEP not in data[0]["name"]
    assert data[0]["description"] == "entA 的客服"
    assert data[0]["builtin"] is False
    assert data[0]["enterprise_owned"] is True
    assert "claude-native-ui" not in names
    assert AGENTB_ID not in [a["id"] for a in data]


def test_list_filters_current_enterprise_for_other_enterprise(monkeypatch):
    cap = _Capture()
    c = TestClient(_app(monkeypatch, cap, claims_fn=MEMBER_B))  # entB 成员
    r = c.get("/v1/ws/agents", cookies={SESSION_COOKIE: _cookie(_valid_sd())})
    data = r.json()["data"]
    by_id = {a["id"]: a for a in data}
    assert BUILTIN_ID not in by_id
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
    # ★ 隔离命门(ADR-028):labels.enterprise_id 由 BFF 据【会话】alias 服务端构造 == ent-aaa。
    assert body == {"agent_id": AGENTA_ID, "host_type": "managed",
                    "labels": {"enterprise_id": ENTA}}


def test_session_create_ignores_forged_enterprise_label(monkeypatch):
    # ★★ 隔离命门(ADR-028 红线 §1):客户端塞 labels:{enterprise_id: 他企业} 试图把别家凭据
    # 注进自己沙箱(窃取)。BFF 绝不转发/合并客户端 labels —— 打到 omnigent 的 labels.enterprise_id
    # 必是【会话】的 alias(ent-aaa),绝非伪造的 "ent-bbb" / 任意客户端 labels。
    cap = _Capture()
    c = TestClient(_app(monkeypatch, cap, claims_fn=MEMBER_A))  # 会话真企业 = ent-aaa
    r = c.post("/v1/ws/sessions", cookies={SESSION_COOKIE: _cookie(_valid_sd())},
               headers={"X-CSRF-Token": "csrf-xyz"},
               json={"agent_id": AGENTA_ID,
                     "labels": {"enterprise_id": ENTB, "cost_control.x": "y", "evil": "1"}})
    assert r.status_code == 200, r.text
    posts = [q for q in cap.requests if q.url.path == "/v1/sessions" and q.method == "POST"]
    assert len(posts) == 1
    body = json.loads(posts[0].content)
    # 伪造的 enterprise_id 被丢弃,只带会话真 alias;客户端其它 labels 也绝不透传。
    assert body["labels"] == {"enterprise_id": ENTA}
    assert body["labels"]["enterprise_id"] == ENTA
    assert body["labels"]["enterprise_id"] != ENTB
    assert "evil" not in body["labels"]
    assert "cost_control.x" not in body["labels"]


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


# ===== (5) per-agent API key(ADR-027 §4'):SDK harness 带字面 key → executor.auth;key 绝不审计 =====

def test_create_sdk_harness_with_api_key_emits_executor_auth(monkeypatch):
    cap = _Capture()
    sink = _FakeSink()
    c = TestClient(_app(monkeypatch, cap, claims_fn=ADMIN_A, sink=sink))
    r = c.post("/v1/ws/agents", cookies={SESSION_COOKIE: _cookie(_valid_sd())},
               headers={"X-CSRF-Token": "csrf-xyz"},
               json={"name": "SDK 助手", "harness": "claude-sdk", "api_key": "sk-x",
                     "base_url": "https://api.example.com"})
    assert r.status_code == 200, r.text
    cfg = _unpack_bundle(_bundle_posts(cap)[0])
    # executor.auth 字面 key(omnigent fork 白名单只收字面值)
    assert cfg["executor"]["config"]["harness"] == "claude-sdk"
    assert cfg["executor"]["auth"]["type"] == "api_key"
    assert cfg["executor"]["auth"]["api_key"] == "sk-x"
    assert cfg["executor"]["auth"]["base_url"] == "https://api.example.com"
    # 审计落 create / allow,且**绝不含 key 值**(仅 has_api_key 布尔)。
    assert len(sink.events) == 1
    ev = sink.events[0]
    assert ev["action"] == "agent:create"
    assert ev["metadata"]["has_api_key"] is True
    assert ev["metadata"]["harness"] == "claude-sdk"
    # 整条审计事件序列化里**不出现** key 值
    assert "sk-x" not in json.dumps(ev)
    # 回前端的 body 也不回显 key 值
    assert "sk-x" not in r.text


def test_create_harness_without_api_key_ok_creds_via_model_config(monkeypatch):
    # ADR-028:凭据走「模型配置」env 注入,per-agent key 不再必填 → 无 key 也能建(不再 400)。
    cap = _Capture()
    sink = _FakeSink()
    c = TestClient(_app(monkeypatch, cap, claims_fn=ADMIN_A, sink=sink))
    r = c.post("/v1/ws/agents", cookies={SESSION_COOKIE: _cookie(_valid_sd())},
               headers={"X-CSRF-Token": "csrf-xyz"},
               json={"name": "SDK 助手", "harness": "codex"})
    assert r.status_code == 200, r.text
    cfg = _unpack_bundle(_bundle_posts(cap)[0])
    assert cfg["executor"]["config"]["harness"] == "codex"
    # 无 per-agent key → bundle 不带 executor.auth(凭据由沙箱 env 注入)
    assert "auth" not in cfg["executor"]


def test_create_openai_agents_harness_with_model(monkeypatch):
    # openai-agents:接 OpenAI 兼容 provider(MiniMax…),凭据走模型配置 env,无 per-agent key。
    cap = _Capture()
    c = TestClient(_app(monkeypatch, cap, claims_fn=ADMIN_A))
    r = c.post("/v1/ws/agents", cookies={SESSION_COOKIE: _cookie(_valid_sd())},
               headers={"X-CSRF-Token": "csrf-xyz"},
               json={"name": "MiniMax 助手", "harness": "openai-agents", "model": "MiniMax-Text-01"})
    assert r.status_code == 200, r.text
    cfg = _unpack_bundle(_bundle_posts(cap)[0])
    assert cfg["executor"]["config"]["harness"] == "openai-agents"
    assert cfg["llm"]["model"] == "MiniMax-Text-01"
    assert "auth" not in cfg["executor"]


def test_create_rejects_env_ref_in_api_key(monkeypatch):
    cap = _Capture()
    sink = _FakeSink()
    c = TestClient(_app(monkeypatch, cap, claims_fn=ADMIN_A, sink=sink))
    r = c.post("/v1/ws/agents", cookies={SESSION_COOKIE: _cookie(_valid_sd())},
               headers={"X-CSRF-Token": "csrf-xyz"},
               json={"name": "SDK 助手", "harness": "claude-sdk", "api_key": "${SECRET}"})
    assert r.status_code == 400, r.text
    assert "literal" in r.json()["reason"]
    # ${} 引用(外泄面)→ BFF 先拒,绝不转发给 fork、不落审计
    assert cap.requests == []
    assert sink.events == []


def test_create_native_harness_no_executor_auth(monkeypatch):
    cap = _Capture()
    c = TestClient(_app(monkeypatch, cap, claims_fn=ADMIN_A))
    r = c.post("/v1/ws/agents", cookies={SESSION_COOKIE: _cookie(_valid_sd())},
               headers={"X-CSRF-Token": "csrf-xyz"},
               json={"name": "原生助手", "harness": "claude-native"})
    assert r.status_code == 200, r.text
    cfg = _unpack_bundle(_bundle_posts(cap)[0])
    # claude-native 用全局共享订阅 → bundle 绝不含 executor.auth
    assert "auth" not in cfg["executor"]


def test_create_native_harness_rejects_api_key(monkeypatch):
    # claude-native 不读 executor.auth(用全局订阅)→ 配 key 无用 → 拒(避免误以为生效)。
    cap = _Capture()
    c = TestClient(_app(monkeypatch, cap, claims_fn=ADMIN_A))
    r = c.post("/v1/ws/agents", cookies={SESSION_COOKIE: _cookie(_valid_sd())},
               headers={"X-CSRF-Token": "csrf-xyz"},
               json={"name": "原生助手", "harness": "claude-native", "api_key": "sk-x"})
    assert r.status_code == 400, r.text
    assert cap.requests == []


def test_create_unknown_harness_400(monkeypatch):
    cap = _Capture()
    c = TestClient(_app(monkeypatch, cap, claims_fn=ADMIN_A))
    r = c.post("/v1/ws/agents", cookies={SESSION_COOKIE: _cookie(_valid_sd())},
               headers={"X-CSRF-Token": "csrf-xyz"},
               json={"name": "助手", "harness": "bogus-harness"})
    assert r.status_code == 400, r.text
    assert cap.requests == []


# ===== (6) 编辑 PUT(ADR-027 §4'):admin 门 + 本企业 own + 同名 re-POST + 审计 configure =====

def test_edit_non_admin_403_no_omnigent(monkeypatch):
    cap = _Capture()
    c = TestClient(_app(monkeypatch, cap, claims_fn=MEMBER_A))  # entA member(非 admin)
    r = c.put(f"/v1/ws/agents/{AGENTA_ID}", cookies={SESSION_COOKIE: _cookie(_valid_sd())},
              headers={"X-CSRF-Token": "csrf-xyz"}, json={"name": "改名"})
    assert r.status_code == 403, r.text
    # can() 在反代前拦 → 完全没打到 omnigent
    assert cap.requests == []


def test_edit_builtin_rejected(monkeypatch):
    cap = _Capture()
    c = TestClient(_app(monkeypatch, cap, claims_fn=ADMIN_A))
    r = c.put(f"/v1/ws/agents/{BUILTIN_ID}", cookies={SESSION_COOKIE: _cookie(_valid_sd())},
              headers={"X-CSRF-Token": "csrf-xyz"}, json={"name": "改内置"})
    assert r.status_code == 403, r.text
    assert "built-in" in r.json()["reason"]
    # 内置(全局)绝不可编辑 → 绝不 re-POST bundle
    assert _bundle_posts(cap) == []


def test_edit_cross_enterprise_rejected(monkeypatch):
    cap = _Capture()
    c = TestClient(_app(monkeypatch, cap, claims_fn=ADMIN_A))  # entA admin 改 entB 的 agent
    r = c.put(f"/v1/ws/agents/{AGENTB_ID}", cookies={SESSION_COOKIE: _cookie(_valid_sd())},
              headers={"X-CSRF-Token": "csrf-xyz"}, json={"name": "越界改"})
    assert r.status_code == 403, r.text
    # 他企业 agent 不可见/不可编辑(隔离)→ 绝不 re-POST bundle
    assert _bundle_posts(cap) == []


def test_edit_own_agent_reposts_same_name_with_new_fields_and_audit(monkeypatch):
    cap = _Capture()
    sink = _FakeSink()
    c = TestClient(_app(monkeypatch, cap, claims_fn=ADMIN_A, sink=sink))  # entA admin 改本企业 agent
    r = c.put(f"/v1/ws/agents/{AGENTA_ID}", cookies={SESSION_COOKIE: _cookie(_valid_sd())},
              headers={"X-CSRF-Token": "csrf-xyz"},
              json={"name": "新客服", "instructions": "新提示词",
                    "harness": "claude-sdk", "api_key": "sk-new"})
    assert r.status_code == 200, r.text
    posts = _bundle_posts(cap)
    assert len(posts) == 1
    cfg = _unpack_bundle(posts[0])
    # **同 omnigent name**(复用旧的 → omnigent upsert/bump version,绝不另建)
    assert cfg["name"] == AGENTA_NAME
    assert cfg["instructions"] == "新提示词"
    # 新展示名落 description 首行;新 key 进 executor.auth(字面)
    assert cfg["description"].split("\n", 1)[0] == "新客服"
    assert cfg["executor"]["auth"]["api_key"] == "sk-new"
    # 审计 configure / allow,绝不含 key 值
    assert len(sink.events) == 1
    ev = sink.events[0]
    assert ev["action"] == "agent:configure"
    assert ev["decision"] == "allow"
    assert ev["metadata"]["has_api_key"] is True
    assert "sk-new" not in json.dumps(ev)
    assert "sk-new" not in r.text


def test_edit_blank_key_clears_executor_auth(monkeypatch):
    # Key-on-edit:留空 api_key → 切到 claude-native(全局订阅)→ 新 bundle 无 executor.auth(旧 key 清)。
    cap = _Capture()
    c = TestClient(_app(monkeypatch, cap, claims_fn=ADMIN_A))
    r = c.put(f"/v1/ws/agents/{AGENTA_ID}", cookies={SESSION_COOKIE: _cookie(_valid_sd())},
              headers={"X-CSRF-Token": "csrf-xyz"},
              json={"name": "回原生", "harness": "claude-native"})
    assert r.status_code == 200, r.text
    cfg = _unpack_bundle(_bundle_posts(cap)[0])
    assert cfg["name"] == AGENTA_NAME
    assert "auth" not in cfg["executor"]
    assert r.json()["has_api_key"] is False


def test_edit_unknown_agent_404(monkeypatch):
    cap = _Capture()
    c = TestClient(_app(monkeypatch, cap, claims_fn=ADMIN_A))
    r = c.put("/v1/ws/agents/ag_nope", cookies={SESSION_COOKIE: _cookie(_valid_sd())},
              headers={"X-CSRF-Token": "csrf-xyz"}, json={"name": "x"})
    assert r.status_code == 404, r.text
    assert _bundle_posts(cap) == []


# ===== (7) 删除 DELETE(admin 门 + 本企业 own;内置/他企业拒;审计 agent:delete)=====

def _deletes(cap: _Capture) -> list[httpx.Request]:
    return [q for q in cap.requests if q.url.path.startswith("/v1/agents/") and q.method == "DELETE"]


def test_delete_non_admin_403_no_omnigent(monkeypatch):
    cap = _Capture()
    c = TestClient(_app(monkeypatch, cap, claims_fn=MEMBER_A))  # entA member(非 admin)
    r = c.delete(f"/v1/ws/agents/{AGENTA_ID}", cookies={SESSION_COOKIE: _cookie(_valid_sd())},
                 headers={"X-CSRF-Token": "csrf-xyz"})
    assert r.status_code == 403, r.text
    assert cap.requests == []   # can() 先于反代 → 完全没打到 omnigent


def test_delete_builtin_rejected(monkeypatch):
    cap = _Capture()
    c = TestClient(_app(monkeypatch, cap, claims_fn=ADMIN_A))
    r = c.delete(f"/v1/ws/agents/{BUILTIN_ID}", cookies={SESSION_COOKIE: _cookie(_valid_sd())},
                 headers={"X-CSRF-Token": "csrf-xyz"})
    assert r.status_code == 403, r.text
    assert "built-in" in r.json()["reason"]
    assert _deletes(cap) == []   # 内置(全局)绝不可删 → 绝不打到 omnigent DELETE


def test_delete_cross_enterprise_rejected(monkeypatch):
    cap = _Capture()
    c = TestClient(_app(monkeypatch, cap, claims_fn=ADMIN_A))  # entA admin 删 entB 的 agent
    r = c.delete(f"/v1/ws/agents/{AGENTB_ID}", cookies={SESSION_COOKIE: _cookie(_valid_sd())},
                 headers={"X-CSRF-Token": "csrf-xyz"})
    assert r.status_code == 403, r.text
    assert _deletes(cap) == []   # 他企业 agent 不可见/不可删(隔离)


def test_delete_own_agent_proxies_and_audits(monkeypatch):
    cap = _Capture()
    sink = _FakeSink()
    c = TestClient(_app(monkeypatch, cap, claims_fn=ADMIN_A, sink=sink))  # entA admin 删本企业 agent
    r = c.delete(f"/v1/ws/agents/{AGENTA_ID}", cookies={SESSION_COOKIE: _cookie(_valid_sd())},
                 headers={"X-CSRF-Token": "csrf-xyz"})
    assert r.status_code == 200, r.text
    assert r.json() == {"deleted": True, "id": AGENTA_ID}
    # 反代到 omnigent DELETE /v1/agents/{id} + 注入身份头
    dels = _deletes(cap)
    assert len(dels) == 1
    assert dels[0].url.path == f"/v1/agents/{AGENTA_ID}"
    assert dels[0].headers.get("x-forwarded-email") == "alice@example.com"
    # 审计 delete / allow(展示名取自 description 首行)
    assert len(sink.events) == 1
    ev = sink.events[0]
    assert ev["action"] == "agent:delete"
    assert ev["decision"] == "allow"
    assert ev["enterprise_id"] == ENTA


def test_delete_unknown_agent_404(monkeypatch):
    cap = _Capture()
    c = TestClient(_app(monkeypatch, cap, claims_fn=ADMIN_A))
    r = c.delete("/v1/ws/agents/ag_nope", cookies={SESSION_COOKIE: _cookie(_valid_sd())},
                 headers={"X-CSRF-Token": "csrf-xyz"})
    assert r.status_code == 404, r.text
    assert _deletes(cap) == []
