# tests/gateway/bff/test_model_config.py —— 模型配置 BFF(ADR-028,每企业统一管模型凭据)TDD
# 红线:
#  - 非 enterprise-admin PUT/GET → 403,且**不写文件**(can() 在写前拦)
#  - admin PUT:写本企业 <alias>.json,置对的 env 名(如 openai api_key → OPENAI_API_KEY),
#    删互斥 auth 选项的 env;值**绝不**进审计/响应/日志;${} 值 → 400
#  - GET:返回各 provider configured/auth_type/has_base_url,**绝无**密钥值
#  - 跨企业:entA 的调用只碰 ent-aaa.json,绝不碰 ent-bbb.json
import json
import time

import httpx
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from services.gateway.app import build_gateway
from services.gateway.bff.middleware import install_bff
from services.gateway.bff.session import SESSION_COOKIE, SessionCodec, SessionData

KEY = Fernet.generate_key()

ENTA = "ent-aaa"
ENTB = "ent-bbb"


def _env(monkeypatch, store_dir):
    monkeypatch.setenv("BFF_SESSION_KEY", KEY.decode())
    monkeypatch.setenv("OIDC_CLIENT_ID", "lite-ai-web")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "s")
    monkeypatch.setenv("OIDC_ISSUER", "http://kc/realms/x")
    monkeypatch.setenv("BFF_REDIRECT_URI", "http://gw/auth/callback")
    # ★ 文件存储指向临时目录 —— 绝不碰真 secrets/。
    monkeypatch.setenv("MODEL_CONFIG_DIR", str(store_dir))
    # 平台默认(claude 全局订阅)探测指向不存在的路径 → 默认 platform_default=False,测试确定性;
    # 需要平台默认的用例自行覆盖此 env 指向真文件(绝不读仓库真 secrets/omnigent.token)。
    monkeypatch.setenv("PLATFORM_ANTHROPIC_TOKEN_FILE", str(store_dir / "no-platform-token"))


def _claims_for(*, sub, org, roles):
    def _fn(_token):
        return {"sub": sub, "organization": [org],
                "realm_access": {"roles": list(roles)},
                "preferred_username": sub, "email": f"{sub}@example.com"}
    return _fn


ADMIN_A = _claims_for(sub="alice", org=ENTA, roles=["enterprise-admin"])
MEMBER_A = _claims_for(sub="bob", org=ENTA, roles=["member"])
ADMIN_B = _claims_for(sub="dave", org=ENTB, roles=["enterprise-admin"])


def _valid_sd():
    return SessionData("at", "rt", int(time.time()) + 300, csrf="csrf-xyz")


def _cookie(sd: SessionData) -> str:
    return SessionCodec(KEY).encode(sd)


class _FakeSink:
    def __init__(self):
        self.events: list[dict] = []

    def put(self, key: str, body: bytes) -> None:
        self.events.append(json.loads(body.decode()))


def _app(monkeypatch, store_dir, *, claims_fn, sink=None):
    _env(monkeypatch, store_dir)
    app = build_gateway(routes={}, with_request_id=False)
    from libs.audit.oss_audit import AuditWriter
    audit = AuditWriter(sink) if sink is not None else None
    install_bff(app, refresh_fn=lambda rt: {}, claims_fn=claims_fn,
                omni_base_url="http://omnigent:8000", audit_writer=audit)
    return app


def _hdr():
    return {"X-CSRF-Token": "csrf-xyz"}


def _ck():
    return {SESSION_COOKIE: _cookie(_valid_sd())}


def _file(store_dir, alias):
    return store_dir / f"{alias}.json"


# ===== (1) 非 admin PUT → 403,不写文件 =====

def test_put_non_admin_403_no_file(monkeypatch, tmp_path):
    c = TestClient(_app(monkeypatch, tmp_path, claims_fn=MEMBER_A))
    r = c.put("/v1/ws/model-config/openai", cookies=_ck(), headers=_hdr(),
              json={"auth_type": "api_key", "value": "sk-secret-xyz"})
    assert r.status_code == 403, r.text
    # 绝不写文件
    assert not _file(tmp_path, ENTA).exists()


def test_get_non_admin_403(monkeypatch, tmp_path):
    c = TestClient(_app(monkeypatch, tmp_path, claims_fn=MEMBER_A))
    r = c.get("/v1/ws/model-config", cookies=_ck())
    assert r.status_code == 403, r.text


# ===== (2) admin PUT:写对 env 名 + 值不外泄 =====

def test_put_openai_api_key_writes_right_env_and_no_secret_leak(monkeypatch, tmp_path):
    sink = _FakeSink()
    c = TestClient(_app(monkeypatch, tmp_path, claims_fn=ADMIN_A, sink=sink))
    SECRET = "sk-proj-topsecret-123"
    r = c.put("/v1/ws/model-config/openai", cookies=_ck(), headers=_hdr(),
              json={"auth_type": "api_key", "value": SECRET,
                    "base_url": "https://api.example.com"})
    assert r.status_code == 200, r.text
    # 文件落对的 env 名 = OPENAI_API_KEY(不是 CODEX_ACCESS_TOKEN)
    creds = json.loads(_file(tmp_path, ENTA).read_text())
    assert creds["OPENAI_API_KEY"] == SECRET
    assert creds["OPENAI_BASE_URL"] == "https://api.example.com"
    assert "CODEX_ACCESS_TOKEN" not in creds
    # 响应绝无密钥值,只回状态
    assert SECRET not in r.text
    body = r.json()
    st = {p["provider"]: p for p in body["providers"]}["openai"]
    assert st["configured"] is True
    assert st["auth_type"] == "api_key"
    assert st["has_base_url"] is True
    # 审计:值绝不出现在整条事件序列化里;只 provider/auth_type/has_base_url 元数据
    assert len(sink.events) == 1
    ev = sink.events[0]
    assert ev["action"] == "model-config:update"
    assert ev["decision"] == "allow"
    assert ev["enterprise_id"] == ENTA
    assert ev["metadata"]["provider"] == "openai"
    assert ev["metadata"]["auth_type"] == "api_key"
    assert ev["metadata"]["has_base_url"] is True
    assert SECRET not in json.dumps(ev)


def test_put_mutually_exclusive_auth_removes_other_env(monkeypatch, tmp_path):
    # 先写 openai subscription(CODEX_ACCESS_TOKEN),再写 api_key(OPENAI_API_KEY)→ 订阅 env 被删。
    c = TestClient(_app(monkeypatch, tmp_path, claims_fn=ADMIN_A))
    r1 = c.put("/v1/ws/model-config/openai", cookies=_ck(), headers=_hdr(),
               json={"auth_type": "subscription", "value": "codex-token-1"})
    assert r1.status_code == 200, r1.text
    creds = json.loads(_file(tmp_path, ENTA).read_text())
    assert creds["CODEX_ACCESS_TOKEN"] == "codex-token-1"
    r2 = c.put("/v1/ws/model-config/openai", cookies=_ck(), headers=_hdr(),
               json={"auth_type": "api_key", "value": "sk-2"})
    assert r2.status_code == 200, r2.text
    creds = json.loads(_file(tmp_path, ENTA).read_text())
    assert creds["OPENAI_API_KEY"] == "sk-2"
    # 互斥:另一个 auth 选项的 env 被删,绝不同存
    assert "CODEX_ACCESS_TOKEN" not in creds


def test_put_anthropic_subscription_writes_oauth_token(monkeypatch, tmp_path):
    c = TestClient(_app(monkeypatch, tmp_path, claims_fn=ADMIN_A))
    r = c.put("/v1/ws/model-config/anthropic", cookies=_ck(), headers=_hdr(),
              json={"auth_type": "subscription", "value": "oauth-tok"})
    assert r.status_code == 200, r.text
    creds = json.loads(_file(tmp_path, ENTA).read_text())
    assert creds["CLAUDE_CODE_OAUTH_TOKEN"] == "oauth-tok"
    assert "ANTHROPIC_API_KEY" not in creds


def test_put_rejects_env_ref_value_400_no_write(monkeypatch, tmp_path):
    c = TestClient(_app(monkeypatch, tmp_path, claims_fn=ADMIN_A))
    r = c.put("/v1/ws/model-config/openai", cookies=_ck(), headers=_hdr(),
              json={"auth_type": "api_key", "value": "${SERVER_SECRET}"})
    assert r.status_code == 400, r.text
    assert "literal" in r.json()["reason"]
    assert not _file(tmp_path, ENTA).exists()


def test_put_rejects_unknown_provider(monkeypatch, tmp_path):
    c = TestClient(_app(monkeypatch, tmp_path, claims_fn=ADMIN_A))
    r = c.put("/v1/ws/model-config/bogus", cookies=_ck(), headers=_hdr(),
              json={"auth_type": "api_key", "value": "x"})
    assert r.status_code == 400, r.text


def test_put_rejects_unsupported_auth_type(monkeypatch, tmp_path):
    # gemini 只有 api_key;subscription 不支持 → 400
    c = TestClient(_app(monkeypatch, tmp_path, claims_fn=ADMIN_A))
    r = c.put("/v1/ws/model-config/gemini", cookies=_ck(), headers=_hdr(),
              json={"auth_type": "subscription", "value": "x"})
    assert r.status_code == 400, r.text


def test_put_rejects_empty_value(monkeypatch, tmp_path):
    c = TestClient(_app(monkeypatch, tmp_path, claims_fn=ADMIN_A))
    r = c.put("/v1/ws/model-config/openai", cookies=_ck(), headers=_hdr(),
              json={"auth_type": "api_key", "value": "   "})
    assert r.status_code == 400, r.text
    assert not _file(tmp_path, ENTA).exists()


# ===== (3) GET:各 provider 状态,无密钥值 =====

def test_get_returns_status_no_secrets(monkeypatch, tmp_path):
    c = TestClient(_app(monkeypatch, tmp_path, claims_fn=ADMIN_A))
    SECRET = "sk-do-not-leak-987"
    c.put("/v1/ws/model-config/openai", cookies=_ck(), headers=_hdr(),
          json={"auth_type": "api_key", "value": SECRET})
    c.put("/v1/ws/model-config/gemini", cookies=_ck(), headers=_hdr(),
          json={"auth_type": "api_key", "value": "gem-key"})
    r = c.get("/v1/ws/model-config", cookies=_ck())
    assert r.status_code == 200, r.text
    # 绝无密钥值
    assert SECRET not in r.text
    assert "gem-key" not in r.text
    by = {p["provider"]: p for p in r.json()["providers"]}
    assert by["openai"]["configured"] is True
    assert by["openai"]["auth_type"] == "api_key"
    assert by["openai"]["has_base_url"] is False
    assert by["gemini"]["configured"] is True
    # 未配的 provider
    assert by["anthropic"]["configured"] is False
    assert by["anthropic"]["auth_type"] is None
    # 状态字段里不含 value / 任何密钥字段(仅状态/元数据,无密钥值)
    for st in r.json()["providers"]:
        assert set(st.keys()) == {"provider", "configured", "auth_type",
                                  "has_base_url", "platform_default", "platform_auth_type"}


# ===== (3b) 平台默认(claude 全局订阅)状态 =====

def test_anthropic_platform_default_when_token_file_present(monkeypatch, tmp_path):
    # 本企业未配 anthropic,但平台有全局订阅(token 文件存在非空)→ platform_default=True(agent 可跑)。
    tok = tmp_path / "platform.token"
    tok.write_text("sk-ant-oat-platform\n")
    c = TestClient(_app(monkeypatch, tmp_path, claims_fn=ADMIN_A))
    # 在 _app(内含 _env,会重设该 env)之后再指向真 token 文件;状态在请求时实时读取。
    monkeypatch.setenv("PLATFORM_ANTHROPIC_TOKEN_FILE", str(tok))
    r = c.get("/v1/ws/model-config", cookies=_ck())
    assert r.status_code == 200, r.text
    by = {p["provider"]: p for p in r.json()["providers"]}
    an = by["anthropic"]
    assert an["configured"] is False           # 本企业未单独配
    assert an["platform_default"] is True       # 但平台默认可用
    assert an["platform_auth_type"] == "subscription"
    # 平台 token 值绝不外泄到响应
    assert "sk-ant-oat-platform" not in r.text
    # 其它 provider 无平台默认
    assert by["openai"]["platform_default"] is False
    assert by["gemini"]["platform_default"] is False


def test_enterprise_config_overrides_platform_default(monkeypatch, tmp_path):
    # 平台有全局订阅,但本企业配了自己的 anthropic → configured=True 覆盖,platform_default 归 False。
    tok = tmp_path / "platform.token"
    tok.write_text("sk-ant-oat-platform")
    c = TestClient(_app(monkeypatch, tmp_path, claims_fn=ADMIN_A))
    monkeypatch.setenv("PLATFORM_ANTHROPIC_TOKEN_FILE", str(tok))
    c.put("/v1/ws/model-config/anthropic", cookies=_ck(), headers=_hdr(),
          json={"auth_type": "api_key", "value": "sk-entA-own"})
    r = c.get("/v1/ws/model-config", cookies=_ck())
    an = {p["provider"]: p for p in r.json()["providers"]}["anthropic"]
    assert an["configured"] is True
    assert an["platform_default"] is False       # 企业配置覆盖平台默认
    assert an["auth_type"] == "api_key"


# ===== (4) 跨企业:只碰自己 alias.json =====

def test_cross_enterprise_isolation_only_touches_own_file(monkeypatch, tmp_path):
    # entB admin 先写 ent-bbb.json;entA admin 写只落 ent-aaa.json,读只见自己的,绝不碰 ent-bbb。
    cB = TestClient(_app(monkeypatch, tmp_path, claims_fn=ADMIN_B))
    cB.put("/v1/ws/model-config/openai", cookies=_ck(), headers=_hdr(),
           json={"auth_type": "api_key", "value": "sk-entB-secret"})
    assert _file(tmp_path, ENTB).exists()
    entb_before = _file(tmp_path, ENTB).read_text()

    cA = TestClient(_app(monkeypatch, tmp_path, claims_fn=ADMIN_A))
    cA.put("/v1/ws/model-config/anthropic", cookies=_ck(), headers=_hdr(),
           json={"auth_type": "api_key", "value": "sk-entA-secret"})
    # entA 只写 ent-aaa.json
    creds_a = json.loads(_file(tmp_path, ENTA).read_text())
    assert creds_a["ANTHROPIC_API_KEY"] == "sk-entA-secret"
    # ent-bbb.json 原封不动(entA 绝不碰别家文件)
    assert _file(tmp_path, ENTB).read_text() == entb_before

    # entA GET 只见自己的配置,绝不见 entB 的 openai
    r = cA.get("/v1/ws/model-config", cookies=_ck())
    by = {p["provider"]: p for p in r.json()["providers"]}
    assert by["anthropic"]["configured"] is True
    assert by["openai"]["configured"] is False   # entB 配的 openai 对 entA 不可见
    assert "sk-entB-secret" not in r.text


# ===== (5) DELETE:移除该 provider 的 env =====

def test_delete_removes_provider_envs(monkeypatch, tmp_path):
    sink = _FakeSink()
    c = TestClient(_app(monkeypatch, tmp_path, claims_fn=ADMIN_A, sink=sink))
    c.put("/v1/ws/model-config/openai", cookies=_ck(), headers=_hdr(),
          json={"auth_type": "api_key", "value": "sk-x", "base_url": "https://api.x"})
    r = c.delete("/v1/ws/model-config/openai", cookies=_ck(), headers=_hdr())
    assert r.status_code == 200, r.text
    creds = json.loads(_file(tmp_path, ENTA).read_text())
    assert "OPENAI_API_KEY" not in creds
    assert "OPENAI_BASE_URL" not in creds
    by = {p["provider"]: p for p in r.json()["providers"]}
    assert by["openai"]["configured"] is False
    # 审计 delete
    actions = [e["action"] for e in sink.events]
    assert "model-config:delete" in actions


def test_delete_non_admin_403(monkeypatch, tmp_path):
    c = TestClient(_app(monkeypatch, tmp_path, claims_fn=MEMBER_A))
    r = c.delete("/v1/ws/model-config/openai", cookies=_ck(), headers=_hdr())
    assert r.status_code == 403, r.text
