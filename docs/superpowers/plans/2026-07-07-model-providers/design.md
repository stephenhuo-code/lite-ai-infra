# Design(设计):模型配置 provider 重整 + 每 provider 独立 harness

> 设计层(HOW)。对应 `spec.md`。所有外部依赖(omnigent fork harness/凭据注入)以**实测为准**;未实测处标 `待探针`,由 plan Task 1 补实。

## 0. 决策留痕(owner 已拍板)
1. **Anthropic 去"平台默认" + 去订阅**:配置页不再显示"平台默认"态;凭据类型**仅 API key**(去 `subscription`);**去掉 compose 全局 `CLAUDE_CODE_OAUTH_TOKEN` 回退**。claude 类 agent 凭据来自企业配置的 `ANTHROPIC_API_KEY`。
2. **去 Gemini,增 MiniMax、DeepSeek**;OpenAI(Codex)保留不动。
3. **MiniMax/DeepSeek 各独立凭据槽 + 各独立 harness**(复制 openai-agents 语义、改名、读自己的槽),使两者可**同时**配置并用。
4. **默认智能体 4→5**:加 deepseek(minimax、deepseek、debby、codex、polly)。

## 1. Provider 表(BFF `services/gateway/bff/model_config.py` `_PROVIDERS`)

as-built → 目标:

```python
_PROVIDERS = {
    "anthropic": {  # 去 subscription:仅 api_key
        "auth": {"api_key": "ANTHROPIC_API_KEY"},
        "base_url_env": "ANTHROPIC_BASE_URL",
    },
    "openai": {     # 不动
        "auth": {"api_key": "OPENAI_API_KEY", "subscription": "CODEX_ACCESS_TOKEN"},
        "base_url_env": "OPENAI_BASE_URL",
    },
    "minimax": {    # 新:独立槽
        "auth": {"api_key": "MINIMAX_API_KEY"},
        "base_url_env": "MINIMAX_BASE_URL",
    },
    "deepseek": {   # 新:独立槽
        "auth": {"api_key": "DEEPSEEK_API_KEY"},
        "base_url_env": "DEEPSEEK_BASE_URL",
    },
    # gemini 删除
}
```

- **`_platform_default_auth` 整体删除**(及 `_provider_status` 里的 `platform_default`/`platform_auth_type` 字段、`_PLATFORM_ANTHROPIC_TOKEN_FILE` 逻辑)。状态回落为二态:`configured` / 未配置。
- 槽命名不重叠:`MINIMAX_*` / `DEEPSEEK_*` / `OPENAI_*` / `ANTHROPIC_*` 四组彼此独立 → 硬保证不串号(spec FR-003/SC-004)。
- 顺序(页面展示):anthropic → openai → minimax → deepseek。

## 2. 契约影响(GET `/v1/ws/model-config` 响应 schema)

`ProviderStatus` 去掉 `platform_default`、`platform_auth_type` 两字段(纯内部 BFF↔前端契约,无外部消费者;非破坏性——前端同批改)。二态:
```json
{"provider":"minimax","configured":false,"auth_type":null,"has_base_url":false}
```
前端 `frontend/src/api/modelConfig.ts`:
- `PROVIDERS` 表:去 gemini,增 minimax/deepseek;anthropic `authOptions` 改为 `['api_key']`;
- `ProviderStatus` 去 `platform_default`/`platform_auth_type`;
- `ModelConfig.tsx`:删"平台默认"徽标/覆盖文案分支(`platformDefault` 相关),二态渲染(已配置/未配置)。

## 3. fork harness 复制(核心)

### 3.1 机制(已实测读码确认)
- harness 名→模块:`omnigent/runtime/harnesses/__init__.py` 的 `_HARNESS_MODULES`。
- 每 harness 模块暴露 `create_app() -> FastAPI`,内部 `ExecutorAdapter(executor_factory=...)`。
- openai-agents 的 factory(`omnigent/inner/openai_agents_sdk_harness.py::_build_openai_agents_sdk_executor`)读 `HARNESS_OPENAI_AGENTS_API_KEY`/`_MODEL`/`_GATEWAY_BASE_URL`,构造 `OpenAIAgentsSDKExecutor`;executor(`openai_agents_sdk_executor.py`)在显式 `api_key` 时用之 + `base_url_override or OPENAI_BASE_URL`(line 453-458)。

### 3.2 新 harness(薄复制,复用 executor)
新增 `omnigent/inner/minimax_harness.py`、`deepseek_harness.py`,各自 `create_app()` 用一个 factory 读**本 provider 的槽**并显式传给共享的 `OpenAIAgentsSDKExecutor`:

```python
# minimax_harness.py（deepseek 同构，换前缀）
_ENV_API_KEY  = "MINIMAX_API_KEY"
_ENV_BASE_URL = "MINIMAX_BASE_URL"
_ENV_MODEL    = "HARNESS_MINIMAX_MODEL"   # 待探针:确认 model 如何从 agent spec 流入

def _factory():
    return OpenAIAgentsSDKExecutor(
        api_key=os.environ.get(_ENV_API_KEY) or None,
        base_url_override=os.environ.get(_ENV_BASE_URL) or None,
        model=os.environ.get(_ENV_MODEL) or None,
        use_responses=False,   # OpenAI 兼容用 /chat/completions（沿用 MiniMax 实测）
    )

def create_app():
    return ExecutorAdapter(executor_factory=_factory).build()
```

注册:`_HARNESS_MODULES` 增 `"minimax": "omnigent.inner.minimax_harness"`、`"deepseek": "omnigent.inner.deepseek_harness"`。

### 3.3 `待探针`（plan Task 1 必须实测确认，禁止猜写进实现）
- **model 流入**:agent spec 的 `model` 字段如何到达自定义 harness?openai-agents 靠 runner 设 `HARNESS_OPENAI_AGENTS_MODEL`;新 harness 名不在 spec-bake 的 env 名映射里 → 需确认 runner 是否按 harness 名派生 `HARNESS_<UPPER>_MODEL`,还是需在 fork 侧补映射。**决策规则**:若 runner 不自动派生,则在 executor spec bake 处按 harness 名补 `HARNESS_<NAME>_MODEL` 映射(最小改动),或让新 harness 读固定 `*_MODEL` 槽 + 默认模型常量兜底。
- **use_responses**:MiniMax/DeepSeek 是否需 `/chat/completions`(=`use_responses=False`)。实测跑通一轮确认。
- **base_url 默认**:MiniMax(如 `https://api.minimaxi.com/v1`)、DeepSeek(如 `https://api.deepseek.com`)——是否要求企业必填,还是 harness 内置默认。**决策规则**:优先企业配置的 `*_BASE_URL`;缺失时 harness 用该 provider 官方默认常量(避免误路由到 api.openai.com)。

## 4. 沙箱注入 env 名单（`deploy/dev/omnigent/config.yaml` `sandbox.docker.env`）

as-built(claude 订阅 + openai + gemini)→ 目标:

```yaml
env:
  - ANTHROPIC_API_KEY          # Anthropic（仅 api key）
  - ANTHROPIC_BASE_URL
  - OPENAI_API_KEY             # OpenAI/Codex
  - OPENAI_BASE_URL
  - CODEX_ACCESS_TOKEN
  - MINIMAX_API_KEY            # 新
  - MINIMAX_BASE_URL           # 新
  - DEEPSEEK_API_KEY           # 新
  - DEEPSEEK_BASE_URL          # 新
  - HARNESS_MINIMAX_MODEL      # 待探针（若需 model 经 env 流入）
  - HARNESS_DEEPSEEK_MODEL
  # 去:CLAUDE_CODE_OAUTH_TOKEN、GEMINI_API_KEY
  - HARNESS_OPENAI_AGENTS_USE_RESPONSES
  - OMNIGENT_RUNNER_ENV_PASSTHROUGH
```

`deploy/dev/omnigent/docker-compose.yml`:
- 删 `CLAUDE_CODE_OAUTH_TOKEN: ${...:?}` 全局注入(去平台 claude 回退,FR-006)。
- 相应 `secrets/omnigent.token` 不再作为全局默认来源(保留文件不删,但不再注入)。
- fork 镜像随新 harness 重编译(`scripts/omnigent_build.sh`);submodule 指针 bump。

> **必须同步 fork 上游 env 白名单**:`MINIMAX_API_KEY`/`MINIMAX_BASE_URL` 不在 `cli.py::_LOCAL_DAEMON_ENV_ALLOWLIST`(仅 `DEEPSEEK_API_KEY` 已在)。`OPENAI_` 前缀已被 `_LOCAL_DAEMON_ENV_PREFIXES` 覆盖但 MINIMAX 无前缀覆盖 → 需在 fork 白名单补 `MINIMAX_API_KEY`/`MINIMAX_BASE_URL`(及 `DEEPSEEK_BASE_URL` 若缺)。`待探针`确认注入路径是否受该白名单约束。

## 5. 默认智能体（`services/gateway/bff/omnigent_proxy.py` `DEFAULT_ENTERPRISE_AGENTS`）

- minimax:`harness="minimax"`(原 `openai-agents`),model 保持 `MiniMax-Text-01`。
- **新增 deepseek**:`harness="deepseek"`,model `deepseek-chat`(`待探针`确认可用模型名),description/instructions 仿现有风格。
- debby/polly:仍 `claude-sdk`(现在依赖企业 `ANTHROPIC_API_KEY`)。
- codex:不动。
- `_default_agent_names()` 自动含 deepseek(集合派生,无需硬编)。
- 顺序:minimax、deepseek、debby、codex、polly。

## 6. 去平台 claude 回退的迁移影响（不静默砍范围）
- 现有企业在补配 `ANTHROPIC_API_KEY` 前,debby/polly 等 claude 类 agent **不可用**——runbook 与 PR 说明必须显式告知,并给补配步骤。
- dev 默认企业 `ent-demo`:`make ws-up` 后需一步"为 ent-demo 配 anthropic/minimax/deepseek 凭据"才能全绿演示(dev 用测试凭据)。

## 7. 授权/隔离/安全红线(不变)
- 授权仍经 `can()`(model-config:read/write/delete → enterprise-admin);跨企业硬隔离。
- 凭据值绝不 log/审计/回显;只收字面值(拒 `${}/$VAR`)。
- 隔离命门:managed 建会话 `labels.enterprise_id` 仍由 BFF 据已认证会话 alias 构造;新槽不改这条。
- 新 env 槽注入仍走"文件值 > 全局 env"解析(fork `docker.py::_resolve_sandbox_env`),未配则不注入(不产生空 env 掩盖)。

## 8. DoR 就绪门(8 项 · 每项须"已决定 / 显式推迟+理由 / 待探针+探针+决策规则")
1. **范围出口**:✅ 已决定 —— 见 spec 范围;Out/推迟明确。
2. **接口契约**:✅ 已决定 —— GET `/v1/ws/model-config` 去两字段(内部契约,前端同批改,无外部消费者;第一个消费者=前端已在本计划内)。
3. **数据模型**:✅ 已决定 —— provider 表 + 每企业 `<alias>.json` env-map(新槽名)。
4. **外部依赖探查事实**:🔍 **待探针**(Task 1)—— ① 新 harness 名注册后 agent 能否选用 ② model 如何流入自定义 harness ③ MiniMax/DeepSeek 经复制 harness 端到端跑通一轮 ④ 上游 env 白名单是否约束新槽。**决策规则见 §3.3/§4**。
5. **行为·边界·并发·威胁**:✅ —— 未配不串号(独立槽);去 claude 回退的迁移态;伪值门;跨企业隔离。
6. **NFR(安全/隔离/性能/parity/拓扑)**:✅ —— 红线 §7;fork 自编译 parity;新增槽不增同步链路阻塞。
7. **验收与测试策略**:✅ —— 见 plan 各 Task 的 TDD + Manual runbook(dev 配三凭据 → minimax/deepseek/claude 各跑一轮)。
8. **关键决策留痕(ADR)**:✅ —— 补 `docs/adr/ADR-028`(as-built 每企业凭据注入 + 本次 provider/harness/去默认增量)。

## 9. 影响文件清单
- `services/gateway/bff/model_config.py`(provider 表、去 platform_default、去 subscription)
- `tests/gateway/bff/test_model_config.py`
- `frontend/src/api/modelConfig.ts`、`frontend/src/pages/ModelConfig.tsx`、`*.test.tsx`
- `third_party/omnigent/omnigent/inner/minimax_harness.py`、`deepseek_harness.py`(新)
- `third_party/omnigent/omnigent/runtime/harnesses/__init__.py`(注册)
- `third_party/omnigent/omnigent/cli.py`(上游 env 白名单,`待探针`确认)
- fork 单测(harness 注册/构造)
- `deploy/dev/omnigent/config.yaml`、`docker-compose.yml`
- `services/gateway/bff/omnigent_proxy.py`(DEFAULT_ENTERPRISE_AGENTS + deepseek)、`tests/gateway/bff/test_agents.py`
- `docs/adr/ADR-028-*.md`(新)、`docs/superpowers/plans/2026-06-28-omnigent-integration/RUNBOOK.md`
- `scripts/omnigent_build.sh` / submodule 指针
