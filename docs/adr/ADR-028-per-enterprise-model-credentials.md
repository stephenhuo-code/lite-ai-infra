# ADR-028: 每企业模型凭据 + 每 provider 独立 harness

- 状态:**Accepted(2026-07-07)**。as-built 部分(每企业凭据注入)自 model-config 落地起生效;本次增量(provider 重整 + 独立 harness)经 PROBE 真链路验证 + owner 拍板。
- 决策人:owner
- 关联:承接 [ADR-027](./ADR-027-agent-library.md)(智能体库)、[ADR-026](./ADR-026-omnigent-integration.md)(omnigent 集成,9a)、[ADR-025](./ADR-025-keycloak-organizations-as-enterprise.md)(企业=KC Org)。遵循 constitution §1(隔离)、§2.4(can())、§2.7(数据路径最小权限)、§5.2(secret 不进仓)、§5.3(parity)、§6.1(审计)。spec/design/PROBE:[`2026-07-07-model-providers/`](../superpowers/plans/2026-07-07-model-providers/)。

> **背景**:9a 初版让所有 agent 共用平台全局 claude 订阅 token(`CLAUDE_CODE_OAUTH_TOKEN`)。owner 要升级为**每企业自管模型凭据**,且支持多个 provider(含两个 OpenAI 兼容的 MiniMax/DeepSeek),并让 Anthropic 与其它 provider 语义一致。此前 model-config 已实现每企业凭据注入,但**从未落 ADR**(代码注释引用 "ADR-028" 却无文件)——本文件补齐 as-built 并记录 2026-07-07 增量。

## Decision

### 1. 每企业模型凭据注入(as-built)
- 企业管理员在「模型配置」页为本企业各 provider 配凭据(API key / 订阅 token + 可选 base_url),BFF 写进 **gitignored** 文件 `secrets/model-config/<alias>.json`(env 名→字面值的扁平 map)。
- omnigent server 只读挂载该目录(`OMNIGENT_MODEL_CREDENTIALS_DIR`)。每次 managed 会话 provision 时,docker sandbox launcher 按 **`session.labels.enterprise_id`** 读本企业文件,把值注入沙箱 env(文件值 > 全局 env,两处都无则不注入)。
- **隔离命门**:`labels.enterprise_id` **只**由 BFF 据【已认证会话】的 alias 服务端构造,绝不合并/转发客户端 labels(否则用户可把别家凭据注进自己沙箱)。alias 经 `_ALIAS_RE` guard(`_`-free、纯 ASCII)→ 文件名无路径穿越。
- **红线**:凭据值绝不 log / 审计 / 回显(GET 只回 configured/auth_type/has_base_url 状态);只收字面值(拒 `${}/$VAR`);授权经 `can(model-config:read/write/delete)` = enterprise-admin;跨企业硬隔离(只碰自己 `<alias>.json`)。

### 2. Provider 集合(增量 2026-07-07)
配置页 provider = **Anthropic (Claude) / OpenAI (Codex) / MiniMax / DeepSeek**(去 Gemini)。四组凭据槽命名**互不重叠**,硬保证不串号:

| Provider | auth | 凭据槽 env |
|---|---|---|
| Anthropic (Claude) | **仅 api_key** | `ANTHROPIC_API_KEY` + `ANTHROPIC_BASE_URL` |
| OpenAI (Codex) | api_key / 订阅 | `OPENAI_API_KEY` / `CODEX_ACCESS_TOKEN` + `OPENAI_BASE_URL` |
| MiniMax | api_key | `MINIMAX_API_KEY` + `MINIMAX_BASE_URL` |
| DeepSeek | api_key | `DEEPSEEK_API_KEY` + `DEEPSEEK_BASE_URL` |

### 3. 每 provider 独立 harness(增量 2026-07-07)
- **问题**:MiniMax、DeepSeek 都是 OpenAI 兼容,初版都靠 openai-agents harness 读同一组 `OPENAI_*` → 无法同时配置(互相覆盖)。
- **决策**:各复制一份 openai-agents harness(复用同一 `OpenAIAgentsSDKExecutor`),**各读自己的凭据槽**,注册为独立 harness 名 `minimax` / `deepseek`。两者可同时配置并各自可用;`OPENAI_*` 槽腾给真正的 OpenAI/Codex。
- **PROBE + verify 实测:每新增一个 provider harness 须改 fork 7 处**(缺一即失败):① `inner/<p>_harness.py` ② `runtime/harnesses/__init__.py::_HARNESS_MODULES` ③ `model_override.py::_SDK_MODEL_OVERRIDE_HARNESSES` ④ `runner/app.py::_HARNESS_MODEL_ENV_KEY`(per-session `/model` 覆盖通道) ⑤ `spec/_omnigent_compat.py::OMNIGENT_HARNESSES`(否则建 agent 400) ⑥ `host/connect.py::HARNESS_CREDENTIAL_ENV_VARS`(否则凭据到不了 runner) ⑦ `runner/app.py::_build_spawn_env_from_spec`(否则 agent spec 声明的 `model` 烤不进 harness、被 harness 默认掩盖——真链路 verify 抓出)。+ Lite-AI 侧 `config.yaml sandbox.docker.env` 列注入槽名。fork 单测 `tests/inner/test_provider_harnesses.py` 锁全 7 处。详见 PROBE.md。
- harness `use_responses=False`(chat/completions);缺 base_url/model 用 provider 官方默认常量(避免误路由到 api.openai.com)。

### 4. Anthropic 去平台默认 + 去订阅(增量 2026-07-07)
- Anthropic 与其它 provider 语义一致:配置页**二态**(已配置/未配置),**无"平台默认"**;凭据类型**仅 API key**(去订阅 token 模式)。
- **平台全局 claude 订阅 token 彻底移除**:不用、不注入、不打进镜像——删 compose 全局 `CLAUDE_CODE_OAUTH_TOKEN` 注入、`config.yaml` 槽、fork `HARNESS_CREDENTIAL_ENV_VARS` 里的它、ws_up.sh 的 token 要求、BFF 的 `_platform_default_auth`(读 `secrets/omnigent.token`)。claude 类 agent(debby/polly)改由企业配置的 `ANTHROPIC_API_KEY` 驱动。
- **迁移影响(不静默砍范围)**:现有企业在补配 `ANTHROPIC_API_KEY` 前,claude 类 agent 不可用——RUNBOOK 与 PR 显式告知。

### 5. 企业默认智能体 4→5(增量 2026-07-07)
- 新企业置备默认得 **minimax、deepseek、debby、codex、polly** 五个本企业 agent。minimax 走 `minimax` harness、deepseek 走 `deepseek` harness(各读自己的槽);debby/polly = claude-sdk;codex 不变。

## Consequences
- 正:多 provider 各自独立可配、可同时用;凭据每企业自管;Anthropic 语义统一;平台不再持有共享 claude 订阅(减少集中密钥面)。
- 负:每新增一个 OpenAI 兼容 provider 需改 fork 6 处 + 重编译(有清单 + 单测护栏 `tests/inner/test_provider_harnesses.py` 兜底);现有企业需补配 anthropic 才能用 claude 类 agent。
- 后续(vN+):模型用量计量/限流(§5.6);provider 健康探活;凭据轮换;把 6 处登记收敛为单一注册点(可 upstream 的 fork 改进)。
