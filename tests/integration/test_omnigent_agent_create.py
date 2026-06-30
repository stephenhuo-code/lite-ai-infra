# tests/integration/test_omnigent_agent_create.py
# 智能体库(ADR-027)· LIVE 集成:BFF 建 agent 的 bundle 必须被【真 omnigent】接受 + 名字归属 round-trip。
#
# 为什么有这个测:BFF 单测用 MockTransport 假装 omnigent 200 —— 它【从不】跑 omnigent 的 YAML/name
# 校验。真 omnigent(spec/validator.py:_AGENT_NAME_PATTERN = ^[a-zA-Z0-9_-]+$)会 400 拒掉
#   (a) 控制符(旧分隔符 U+001F),(b) 任何非 ASCII 展示名(如中文)落进 name。
# 这个 LIVE 测正面打真服务,堵住"单测绿、上线 400"的缝。
#
# 默认不跑(`-m 'not integration'`);omnigent 不可达时干净 skip(CI 无 omnigent 仍绿)。
import socket

import httpx
import pytest

from services.gateway.bff.omnigent_proxy import (
    _ENT_SEP,
    _build_bundle_bytes,
    _decode_description,
    _encode_description,
    _enterprise_name,
    _split_enterprise,
)

pytestmark = pytest.mark.integration

OMNI = "http://127.0.0.1:8900"
HOST, PORT = "127.0.0.1", 8900
EMAIL = {"X-Forwarded-Email": "alice@test"}


def _omni_up() -> bool:
    try:
        with socket.create_connection((HOST, PORT), timeout=1):
            return True
    except OSError:
        return False


@pytest.fixture(autouse=True)
def _require_omnigent():
    if not _omni_up():
        pytest.skip(f"omnigent not reachable at {OMNI} — skipping live round-trip")


def _post_bundle(bundle: bytes) -> httpx.Response:
    files = {"bundle": ("bundle.tar.gz", bundle, "application/gzip")}
    return httpx.post(f"{OMNI}/v1/agents", files=files, headers=EMAIL,
                      timeout=30, trust_env=False)


def _get_agents() -> list[dict]:
    r = httpx.get(f"{OMNI}/v1/agents", headers=EMAIL, timeout=30, trust_env=False)
    r.raise_for_status()
    body = r.json()
    items = body.get("data") if isinstance(body, dict) else body
    return items if isinstance(items, list) else []


def test_bff_bundle_accepted_and_name_roundtrips_live():
    """BFF 搭的 bundle(企业前缀 name + 中文展示名落 description)→ 真 omnigent 200,
    且 name 前缀(企业归属)与展示名都原样 round-trip。这是抓到 U+001F 400 bug 的那一步。"""
    alias = "ent-demo"
    display = "客服助手"               # 中文:旧设计把它塞进 name 会被 omnigent 400
    user_desc = "处理客户咨询"

    # —— 完全照 BFF create_agent 的口径搭 bundle ——
    name = _enterprise_name(alias, display)
    assert name.partition(_ENT_SEP)[0] == alias            # 前缀 = 企业归属
    bundle = _build_bundle_bytes(
        name=name, instructions="你是客服", harness="claude-native",
        model=None, description=_encode_description(display, user_desc))

    # —— POST 真 omnigent:必须 200(旧 U+001F 在此是 400) ——
    r = _post_bundle(bundle)
    assert r.status_code == 200, f"expected 200 from live omnigent, got {r.status_code}: {r.text}"
    agent_id = r.json()["id"]
    assert agent_id

    # —— GET 回来:name 前缀完好(归属可还原)、展示名/用户描述从 description 原样还原 ——
    match = next((a for a in _get_agents() if a.get("id") == agent_id), None)
    assert match is not None, "created agent not found in GET /v1/agents"
    owner, _slug = _split_enterprise(match["name"])
    assert owner == alias                                   # 企业归属 round-trip 完好
    got_display, got_desc = _decode_description(match.get("description", ""))
    assert got_display == display                           # 中文展示名原样回来
    assert got_desc == user_desc


def test_builtin_name_parses_as_builtin_live():
    """真 omnigent 的内置模板(name 无 "_" 分隔符)→ 被识别为内置(无企业归属、全局共享)。"""
    builtins = [a for a in _get_agents() if _ENT_SEP not in a.get("name", "")]
    assert builtins, "expected at least one built-in (no-SEP) agent from live omnigent"
    for a in builtins:
        owner, display = _split_enterprise(a["name"])
        assert owner is None                                # 无前缀 = 内置(全局)
        assert display == a["name"]                         # 内置展示名 = 其 omnigent name


def test_control_char_name_rejected_live():
    """回归钉:旧分隔符 U+001F(控制符)落进 name → 真 omnigent **必 400**(就是上线时的 bug)。
    证明我们换分隔符不是多余的:控制符确实进不了 omnigent name。"""
    bad = _build_bundle_bytes(
        name="ent-demo\x1f客服助手", instructions=None, harness="claude-native",
        model=None, description=None)
    r = _post_bundle(bad)
    assert r.status_code == 400, f"expected live omnigent to reject U+001F name, got {r.status_code}"
