# 企业默认智能体模板(Default Enterprise Agents) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新企业创建/置备时自动获得 4 个可编辑的本企业默认智能体:minimax、debby、codex、polly。

**Architecture:** 不新增 omnigent fork clone 端点。BFF 维护一组受控默认模板定义,通过现有 `_build_bundle_bytes(...)` 和 omnigent `POST /v1/agents` 幂等创建缺失的企业 agent。默认 agent 后续就是普通本企业 agent,管理员编辑/删除复用现有 `PUT/DELETE /v1/ws/agents/{id}`。

**Tech Stack:** Python 3.12 + FastAPI/BFF(`services/gateway/bff/omnigent_proxy.py`), httpx MockTransport 单测, dev/ops Python 脚本, TypeScript + Vite 前端文案/测试。

## Global Constraints

- **默认模板固定为 4 个**:`minimax`、`debby`、`codex`、`polly`。
- **不做 fork clone**:不得新增 `POST /v1/agents/{id}/copy`,不得要求重编译 omnigent 仅为默认模板。
- **企业归属编码**:沿用 ADR-027 as-built,`name = "<alias>_<ascii-slug>-<rand>"`,展示名落 `description` 首行。
- **alias 不变量**:`^[a-zA-Z0-9-]+$`(`_`-free),复用 `_resolve_ctx`/初始化函数校验。
- **凭据红线**:默认模板不写 `executor.auth`,不保存 per-agent key;运行凭据走企业模型配置或平台默认。
- **授权红线**:系统置备创建默认 agent 不代表普通用户可绕过授权;用户编辑/删除仍走 `can(agent:configure/delete)`。
- 需求见 `docs/superpowers/plans/2026-07-04-agent-template-copies/spec.md`;设计见同目录 `design.md`;ADR 增量写入 `docs/adr/ADR-027-agent-library.md`。

---

## File Structure

- Modify: `services/gateway/bff/omnigent_proxy.py`
  增加默认模板 dataclass/常量、幂等初始化函数,复用现有 bundle 构造和 name/description 编码。
- Create: `scripts/provision_default_agents.py`
  dev/ops 补种入口,接收企业 alias,调用默认模板初始化。
- Modify: `scripts/ws_up.sh` 或 `Makefile`
  在 dev workspace 置备链路中调用默认 agent 初始化。
- Modify: `tests/gateway/bff/test_agents.py`
  覆盖默认模板定义、幂等创建、补缺、不覆盖、跨企业前缀。
- Create: `tests/scripts/test_provision_default_agents.py` 或扩展现有脚本测试
  验证脚本参数、错误输出、调用核心初始化。
- Modify: `frontend/src/pages/Agents.tsx` and `frontend/src/pages/Agents.test.tsx`
  更新页面文案,移除"内置模板 + 本企业创建"语义。
- Modify: `services/gateway/bff/omnigent_proxy.py` and `tests/gateway/bff/test_agents.py`
  企业侧列表隐藏 omnigent 内置模板,只返回本企业 agent。
- Modify: `docs/adr/ADR-027-agent-library.md`
  记录默认企业模板增量:4 个默认 agent,不 fork clone。
- Modify: `docs/superpowers/plans/2026-06-28-omnigent-integration/RUNBOOK.md`
  更新智能体库验收步骤。

---

## Task 1: BFF 默认模板定义 + bundle 生成单元测试

**Files:**
- Modify: `services/gateway/bff/omnigent_proxy.py`
- Test: `tests/gateway/bff/test_agents.py`

**Interfaces:**
- Produces:
  - `DefaultAgentTemplate`
  - `DEFAULT_ENTERPRISE_AGENTS`
  - `_default_agent_names() -> set[str]`
- Consumes existing:
  - `_build_bundle_bytes(...)`
  - `_enterprise_name(alias, display)`
  - `_encode_description(display, user_desc)`

- [ ] **Step 1: 写失败测试:默认模板集合准确**

Append to `tests/gateway/bff/test_agents.py`:

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/gateway/bff/test_agents.py::test_default_enterprise_agent_templates_are_fixed_four -q`
Expected: FAIL with `AttributeError: DEFAULT_ENTERPRISE_AGENTS`.

- [ ] **Step 3: 实现默认模板定义**

In `services/gateway/bff/omnigent_proxy.py`, add imports near the top:

```python
from dataclasses import dataclass
```

Add near harness constants:

```python
@dataclass(frozen=True)
class DefaultAgentTemplate:
    key: str
    display_name: str
    harness: str
    model: str | None
    description: str
    instructions: str


DEFAULT_ENTERPRISE_AGENTS: tuple[DefaultAgentTemplate, ...] = (
    DefaultAgentTemplate(
        key="minimax",
        display_name="minimax",
        harness="openai-agents",
        model="MiniMax-Text-01",
        description="OpenAI 兼容 provider 模板,默认用于 MiniMax。",
        instructions="你是 minimax 智能体,使用企业配置的 OpenAI 兼容 provider 回答问题。",
    ),
    DefaultAgentTemplate(
        key="debby",
        display_name="debby",
        harness="claude-sdk",
        model=None,
        description="多视角讨论与审查助手。",
        instructions="你是 Debby,负责从多个角度审查问题、提出反例和改进建议。",
    ),
    DefaultAgentTemplate(
        key="codex",
        display_name="codex",
        harness="codex",
        model=None,
        description="代码实现和修改助手。",
        instructions="你是 Codex,负责阅读代码、提出实现计划并谨慎修改项目文件。",
    ),
    DefaultAgentTemplate(
        key="polly",
        display_name="polly",
        harness="claude-sdk",
        model=None,
        description="任务拆解与协作编排助手。",
        instructions="你是 Polly,负责把目标拆成可执行任务,协调多个实现者并汇总结果。",
    ),
)


def _default_agent_names() -> set[str]:
    return {t.display_name for t in DEFAULT_ENTERPRISE_AGENTS}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/gateway/bff/test_agents.py::test_default_enterprise_agent_templates_are_fixed_four -q`
Expected: PASS.

- [ ] **Step 5: 提交**

```bash
git add services/gateway/bff/omnigent_proxy.py tests/gateway/bff/test_agents.py
git commit -m "feat(9a/default-agents): define four enterprise default agent templates"
```

---

## Task 2: 幂等初始化函数(创建缺失默认 agent)

**Files:**
- Modify: `services/gateway/bff/omnigent_proxy.py`
- Test: `tests/gateway/bff/test_agents.py`

**Interfaces:**
- Produces:
  - `DefaultAgentSeedResult(created: list[str], skipped: list[str])`
  - `ensure_default_agents_for_enterprise(alias: str, *, omni_base_url: str = "http://omnigent:8000", identity_email: str = "system@lite-ai.local", transport: httpx.BaseTransport | None = None) -> DefaultAgentSeedResult`
- Consumes:
  - `GET /v1/agents`
  - `POST /v1/agents`
  - `_split_enterprise`
  - `_decode_description`
  - `_build_bundle_bytes`

- [ ] **Step 1: 扩展测试 capture 支持返回创建的 name/description**

In `tests/gateway/bff/test_agents.py`, update `_Capture.handler` POST `/v1/agents` branch to unpack bundle and append the created agent:

```python
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
```

- [ ] **Step 2: 写失败测试:空企业创建 4 个默认 agent**

Append:

```python
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
```

- [ ] **Step 3: 写失败测试:重复运行不重复创建**

Append:

```python
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
```

- [ ] **Step 4: 写失败测试:已有 debby 只补缺失**

Append:

```python
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
```

- [ ] **Step 5: 跑测试确认失败**

Run: `uv run pytest tests/gateway/bff/test_agents.py -k "ensure_default_agents" -q`
Expected: FAIL with missing `ensure_default_agents_for_enterprise`.

- [ ] **Step 6: 实现结果类型与初始化函数**

In `services/gateway/bff/omnigent_proxy.py`, add:

```python
@dataclass(frozen=True)
class DefaultAgentSeedResult:
    created: list[str]
    skipped: list[str]
```

Add module-level function after `_build_bundle_bytes(...)`:

```python
def ensure_default_agents_for_enterprise(
    alias: str,
    *,
    omni_base_url: str = "http://omnigent:8000",
    identity_email: str = "system@lite-ai.local",
    transport: httpx.BaseTransport | None = None,
) -> DefaultAgentSeedResult:
    if not _ALIAS_RE.fullmatch(alias):
        raise ValueError("enterprise alias incompatible with agent library")

    base = omni_base_url.rstrip("/")
    headers = {"Accept": "application/json", _IDENTITY_HEADER: identity_email}
    created: list[str] = []
    skipped: list[str] = []

    with httpx.Client(base_url=base, timeout=30, trust_env=False, transport=transport) as cli:
        r = cli.get("/v1/agents", headers=headers)
        r.raise_for_status()
        body = r.json()
        raw = body.get("data") if isinstance(body, dict) else body
        agents = raw if isinstance(raw, list) else []

        existing: set[str] = set()
        for agent in agents:
            owner, _ = _split_enterprise(agent.get("name", ""))
            if owner != alias:
                continue
            display, _ = _decode_description(agent.get("description", "") or "")
            if display:
                existing.add(display)

        for template in DEFAULT_ENTERPRISE_AGENTS:
            if template.display_name in existing:
                skipped.append(template.display_name)
                continue
            bundle = _build_bundle_bytes(
                name=_enterprise_name(alias, template.display_name),
                instructions=template.instructions,
                harness=template.harness,
                model=template.model,
                description=_encode_description(template.display_name, template.description),
                api_key=None,
                base_url=None,
            )
            resp = cli.post(
                "/v1/agents",
                files={"bundle": ("bundle.tar.gz", bundle, "application/gzip")},
                headers=headers,
            )
            resp.raise_for_status()
            created.append(template.display_name)

    return DefaultAgentSeedResult(created=created, skipped=skipped)
```

- [ ] **Step 7: 跑测试确认通过**

Run: `uv run pytest tests/gateway/bff/test_agents.py -k "default_enterprise_agent_templates or ensure_default_agents" -q`
Expected: PASS.

- [ ] **Step 8: 提交**

```bash
git add services/gateway/bff/omnigent_proxy.py tests/gateway/bff/test_agents.py
git commit -m "feat(9a/default-agents): seed missing default agents idempotently"
```

---

## Task 3: dev/ops 置备脚本

**Files:**
- Create: `scripts/provision_default_agents.py`
- Test: `tests/scripts/test_provision_default_agents.py`

**Interfaces:**
- CLI:
  - `uv run python scripts/provision_default_agents.py --enterprise ent-demo`
  - env `OMNIGENT_BASE_URL` default `http://127.0.0.1:8900`
  - env `OMNIGENT_IDENTITY_EMAIL` default `system@lite-ai.local`

- [ ] **Step 1: 写脚本测试**

Create `tests/scripts/test_provision_default_agents.py`:

```python
from scripts import provision_default_agents as p


class _Result:
    created = ["minimax", "debby"]
    skipped = ["codex", "polly"]


def test_main_calls_seed_with_enterprise(monkeypatch, capsys):
    seen = {}

    def fake_seed(alias, *, omni_base_url, identity_email, transport=None):
        seen["alias"] = alias
        seen["base"] = omni_base_url
        seen["email"] = identity_email
        return _Result()

    monkeypatch.setattr(p, "ensure_default_agents_for_enterprise", fake_seed)
    rc = p.main(["--enterprise", "ent-demo", "--omni-base-url", "http://omni"])

    assert rc == 0
    assert seen == {"alias": "ent-demo", "base": "http://omni", "email": "system@lite-ai.local"}
    out = capsys.readouterr().out
    assert "created: minimax, debby" in out
    assert "skipped: codex, polly" in out
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/scripts/test_provision_default_agents.py -q`
Expected: FAIL because script does not exist.

- [ ] **Step 3: 创建脚本**

Create `scripts/provision_default_agents.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os

from services.gateway.bff.omnigent_proxy import ensure_default_agents_for_enterprise


def _fmt(items: list[str]) -> str:
    return ", ".join(items) if items else "none"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Provision default enterprise agents")
    parser.add_argument("--enterprise", required=True, help="KC organization alias, e.g. ent-demo")
    parser.add_argument("--omni-base-url", default=os.getenv("OMNIGENT_BASE_URL", "http://127.0.0.1:8900"))
    parser.add_argument("--identity-email", default=os.getenv("OMNIGENT_IDENTITY_EMAIL", "system@lite-ai.local"))
    args = parser.parse_args(argv)

    result = ensure_default_agents_for_enterprise(
        args.enterprise,
        omni_base_url=args.omni_base_url,
        identity_email=args.identity_email,
    )
    print(f"default agents for `{args.enterprise}` ready")
    print(f"  created: {_fmt(result.created)}")
    print(f"  skipped: {_fmt(result.skipped)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/scripts/test_provision_default_agents.py -q`
Expected: PASS.

- [ ] **Step 5: 提交**

```bash
git add scripts/provision_default_agents.py tests/scripts/test_provision_default_agents.py
git commit -m "feat(9a/default-agents): add dev ops provision script"
```

---

## Task 4: 接入 dev workspace 置备链路

**Files:**
- Modify: `scripts/ws_up.sh`
- Modify: `Makefile`
- Test: `tests/scripts/test_ws_up.py` if present, otherwise add a lightweight shell text test under `tests/scripts/`.

**Interfaces:**
- Consumes Task 3 CLI.
- Produces `make ws-up` 后 ent-demo 默认 agent 就绪。

- [ ] **Step 1: 找到 ws-up 中 omnigent ready 后的位置**

Run: `sed -n '1,260p' scripts/ws_up.sh`
Expected: 找到 `make provision-orgs` 和 omnigent/server ready 检查之后的阶段。

- [ ] **Step 2: 加调用**

Add after omnigent is reachable:

```bash
echo "==> Provision default enterprise agents"
uv run python scripts/provision_default_agents.py --enterprise "${EID:-ent-demo}" --omni-base-url "http://127.0.0.1:8900"
```

- [ ] **Step 3: 如果 Makefile 需要显式目标,加 `provision-default-agents`**

In `Makefile`:

```make
provision-default-agents: ; uv run python scripts/provision_default_agents.py --enterprise $(EID)
```

- [ ] **Step 4: 跑语法/脚本测试**

Run: `bash -n scripts/ws_up.sh && uv run pytest tests/scripts/test_provision_default_agents.py -q`
Expected: PASS.

- [ ] **Step 5: 提交**

```bash
git add scripts/ws_up.sh Makefile tests/scripts/test_provision_default_agents.py
git commit -m "chore(9a/default-agents): provision defaults during dev workspace startup"
```

---

## Task 5: 智能体库只显示本企业 agent + 前端文案

**Files:**
- Modify: `frontend/src/pages/Agents.tsx`
- Modify: `frontend/src/pages/Agents.test.tsx`
- Modify: `services/gateway/bff/omnigent_proxy.py`
- Modify: `tests/gateway/bff/test_agents.py`

**Interfaces:**
- Current API remains `GET /v1/ws/agents`.

- [ ] **Step 1: 更新页面文案**

In `frontend/src/pages/Agents.tsx`, change the subtitle from:

```tsx
本企业可见的智能体:平台内置模板 + 本企业创建。对话开始时从中选用。
```

to:

```tsx
本企业智能体。新企业默认包含 minimax、debby、codex 和 polly,企业管理员可编辑。
```

- [ ] **Step 2: 改 BFF 列表过滤,隐藏内置**

Replace list filter in `agents()` so `owner is None` is skipped:

```python
if owner != alias:
    continue
```

Expected: screenshot no longer shows `内置` cards once default enterprise agents exist.

- [ ] **Step 3: 更新 BFF 列表测试断言**

In `tests/gateway/bff/test_agents.py`, update old built-in visibility tests so:

```python
def test_list_filters_per_enterprise_and_strips_prefix(monkeypatch):
    cap = _Capture()
    c = TestClient(_app(monkeypatch, cap, claims_fn=ADMIN_A))
    r = c.get("/v1/ws/agents", cookies={SESSION_COOKIE: _cookie(_valid_sd())})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    names = [d["name"] for d in data]
    assert names == [AGENTA_DISPLAY]
    assert all(d["enterprise_owned"] and not d["builtin"] for d in data)
    assert "claude-native-ui" not in names
    assert AGENTB_DISPLAY not in names
```

Expected:内置不再作为企业可见项返回。

- [ ] **Step 4: 更新前端测试断言**

Run: `cd frontend && npx vitest run src/pages/Agents.test.tsx`
Expected before update:可能因文案变更失败。Update expected text to include `minimax、debby、codex 和 polly`.

- [ ] **Step 5: 跑相关验证**

Run:
```bash
uv run pytest tests/gateway/bff/test_agents.py -k list_filters -q
cd frontend && npx vitest run src/pages/Agents.test.tsx src/api/omnigent.test.ts
```
Expected: PASS.

- [ ] **Step 6: 提交**

```bash
git add frontend/src/pages/Agents.tsx frontend/src/pages/Agents.test.tsx services/gateway/bff/omnigent_proxy.py tests/gateway/bff/test_agents.py
git commit -m "feat(9a/default-agents): align agent library UI with enterprise defaults"
```

---

## Task 6: ADR 与 runbook 更新

**Files:**
- Modify: `docs/adr/ADR-027-agent-library.md`
- Modify: `docs/superpowers/plans/2026-06-28-omnigent-integration/RUNBOOK.md`

**Interfaces:**
- Documents the decision and manual acceptance path.

- [ ] **Step 1: ADR-027 增加默认模板增量**

Append a section:

```markdown
### 6. 增量(2026-07-05):企业创建时默认智能体模板
- 新企业创建/置备时默认获得 4 个本企业 agent:minimax、debby、codex、polly。
- 默认 agent 由 Lite AI BFF 维护的模板定义生成,复用现有 `POST /v1/agents`;不新增 omnigent fork clone 端点。
- 默认 agent 是普通本企业资源,企业管理员可编辑/删除;普通成员不可改删。
- 凭据不进入 agent bundle,继续由企业模型配置/平台默认注入。
```

- [ ] **Step 2: runbook 更新智能体库验收**

Update the agent library section to include:

```markdown
**你该看到什么**:智能体库里有 minimax、debby、codex、polly 四个"本企业"智能体,不再并列展示"内置"模板卡片。管理员能编辑 debby,能删除 polly;刷新后结果保持。普通成员没有编辑/删除入口。
```

- [ ] **Step 3: 文档自检**

Run:

```bash
rg -n "^## Task .*Fork|submodule 指针|AGENT_SEED_DIR|\\.seeding|O_EXCL|服务端 clone" \
  docs/superpowers/plans/2026-07-04-agent-template-copies.md \
  docs/superpowers/plans/2026-07-04-agent-template-copies/spec.md \
  docs/superpowers/plans/2026-07-04-agent-template-copies/design.md \
  | rg -v "rg -n|Expected:|Self-Review|移除"
```

Expected: no matches. Mentions that explicitly reject fork copy are allowed; executable fork tasks are not.

- [ ] **Step 4: 提交**

```bash
git add docs/adr/ADR-027-agent-library.md docs/superpowers/plans/2026-06-28-omnigent-integration/RUNBOOK.md
git commit -m "docs(9a/default-agents): record enterprise default agent decision"
```

---

## Final Verification

- [ ] `uv run pytest tests/gateway/bff/test_agents.py -k "default_enterprise_agent_templates or ensure_default_agents" -q`
- [ ] `uv run pytest tests/scripts/test_provision_default_agents.py -q`
- [ ] `bash -n scripts/ws_up.sh`
- [ ] `cd frontend && npx vitest run src/pages/Agents.test.tsx src/api/omnigent.test.ts`
- [ ] `make lint`

## Manual Acceptance Runbook

1. 起本地 workspace: `make ws-up`
   - 你应该看到 omnigent 和 gateway 都起来,并打印默认 agent created/skipped 摘要。
2. 打开前端智能体库。
   - 你应该看到 minimax、debby、codex、polly,并且它们是"本企业";不再看到"内置"卡片。
3. 用企业管理员编辑 debby 的描述或 prompt。
   - 保存成功,刷新后仍是修改后的内容。
4. 删除 polly。
   - polly 从本企业列表消失;再次刷新不会因为普通列表读取自动复活。
5. 再运行 `make provision-default-agents EID=ent-demo`。
   - 缺失的 polly 会被补回,已有 minimax/debby/codex 不被覆盖。

## Self-Review

- [x] 移除了 fork copy 端点任务、submodule bump、旧种子标记和首次进库写副作用。
- [x] 覆盖 owner 指定的 4 个默认智能体。
- [x] 保留企业隔离、can() 编辑/删除门、无 per-agent 凭据红线。
- [x] 提供已存在企业补种路径,并明确不覆盖管理员修改。
