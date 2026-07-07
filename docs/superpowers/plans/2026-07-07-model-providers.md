# 模型配置 provider 重整 + 每 provider 独立 harness — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans。逐 Task/Step 勾 `- [ ]`,TDD(红→绿→重构),实时更新状态。
> **Spec**:`2026-07-07-model-providers/spec.md` · **Design**:`2026-07-07-model-providers/design.md`

**Goal:** 配置页 provider = {Anthropic(仅 api key、无平台默认), OpenAI(Codex), MiniMax, DeepSeek}(去 Gemini);MiniMax/DeepSeek 各独立凭据槽 + 各独立 harness 可同时配置并用;默认智能体 4→5(加 deepseek);去平台 claude 全局回退。

**Tech Stack:** Python 3.12 FastAPI/BFF(httpx MockTransport 单测)、omnigent fork(Python harness + 自编译镜像)、TypeScript+Vite 前端、docker-compose。

## Global Constraints
- **凭据红线**:值绝不 log/审计/回显;只收字面值(拒 `${}/$VAR`);每企业硬隔离(只碰自己 `<alias>.json`)。
- **授权红线**:model-config 写/读经 `can()`(enterprise-admin)。
- **不串号**:MiniMax/DeepSeek/OpenAI/Anthropic 四组 env 槽命名互不重叠;未配 provider 的 agent 明确不可用,绝不回落别家凭据。
- **不静默砍范围**:去平台 claude 回退导致"现有企业补配前 claude agent 不可用",必须在 runbook/PR 显式告知。
- **探针先行**:Task 1 未跑通前,不把猜测的 fork model-flow/endpoint 写进实现(design §3.3/§4 决策规则)。

---

## Task 1: 探针 — 复制 harness 端到端跑通并记事实(DoR #4)

**目的:** 用**最小真实链路**确认 design §3.3/§4 的 4 个未知,把实测写成事实,后续实现以此为准(禁猜)。

**Files:** 临时改 `third_party/omnigent/...`(探针分支/worktree,可弃);记录写 `2026-07-07-model-providers/PROBE.md`。

- [ ] **Step 1: 起栈基线**
  `make ws-up`,确认 omnigent server/host 就绪、现有 minimax(openai-agents)默认 agent 能对话(用 dev 测试 OpenAI 兼容凭据)。记当前 minimax 走 `OPENAI_*` 的实况。
- [ ] **Step 2: 加最小 `minimax_harness.py` + 注册**
  按 design §3.2 写薄 harness 读 `MINIMAX_API_KEY`/`MINIMAX_BASE_URL`/`HARNESS_MINIMAX_MODEL`;`_HARNESS_MODULES` 注册 `"minimax"`;`config.yaml` env 加三槽;重编译镜像。
- [ ] **Step 3: 建一个 harness=minimax 的 agent 并对话**
  经 BFF 建(或直接 omnigent POST /v1/agents)一个 `harness=minimax` 的 agent,配 `MINIMAX_*` 到 `secrets/model-config/ent-demo.json`,发一条消息。
- [ ] **Step 4: 记事实(PROBE.md)**
  回答:① 新 harness 名能否被 agent 选用并起 runner ② `model` 字段实际经哪个 env 到达 harness(是否 runner 自动派生 `HARNESS_MINIMAX_MODEL`,还是需 fork 补映射)③ `use_responses` 需否 False ④ base_url 缺失时行为 ⑤ 上游 `cli.py::_LOCAL_DAEMON_ENV_ALLOWLIST` 是否拦 `MINIMAX_*`。**每条附命令 + 观察到的输出证据。**
- [ ] **Step 5: 据实测敲定决策规则**
  在 PROBE.md 末尾把 design 的 `待探针` 项改为"已决定"(model-flow 方案、endpoint 默认、白名单补项)。
- [ ] **Step 6: 提交探针记录**（探针代码可丢弃,只留 PROBE.md）
  `git add docs/superpowers/plans/2026-07-07-model-providers/PROBE.md && git commit -m "probe(9a/providers): minimax harness copy end-to-end facts"`

> **人参与点**:探针结果研判 + DoR #4 过门由 owner 拍板后再进 Task 2。

---

## Task 2: fork — minimax/deepseek harness + 注册 + 白名单 + 重编译

**Files:**
- Create: `third_party/omnigent/omnigent/inner/minimax_harness.py`、`deepseek_harness.py`
- Modify: `third_party/omnigent/omnigent/runtime/harnesses/__init__.py`
- Modify: `third_party/omnigent/omnigent/cli.py`(env 白名单,按 Task 1 结论)
- Test: fork 侧 `tests/inner/test_*_harness.py`(注册可解析 + factory 读对槽)
- Modify: submodule 指针 + `scripts/omnigent_build.sh` 触发

- [ ] **Step 1: 写失败测试** — `_HARNESS_MODULES` 含 `minimax`/`deepseek`;各 factory 在设了 `MINIMAX_API_KEY`/`DEEPSEEK_API_KEY` 时构造出带对应 api_key/base_url 的 executor(monkeypatch env)。
- [ ] **Step 2: 跑测试确认失败(KeyError/ImportError)。**
- [ ] **Step 3: 实现两 harness 模块**(按 Task 1 敲定的 model-flow/use_responses/默认 endpoint)。
- [ ] **Step 4: 注册进 `_HARNESS_MODULES`;白名单补 `MINIMAX_*`(及缺的 `DEEPSEEK_BASE_URL`)。**
- [ ] **Step 5: 跑 fork 单测确认绿。**
- [ ] **Step 6: 重编译镜像 + bump submodule 指针。**
  `scripts/omnigent_build.sh`;`git add third_party/omnigent`。
- [ ] **Step 7: 提交** `feat(9a/providers): minimax+deepseek harness (copy of openai-agents, own cred slots) + bump submodule`

---

## Task 3: BFF provider 表(anthropic 仅 api key、去 platform_default、去 gemini、增 minimax/deepseek)

**Files:** Modify `services/gateway/bff/model_config.py`;Test `tests/gateway/bff/test_model_config.py`

- [ ] **Step 1: 改测试** — provider 集合 = {anthropic, openai, minimax, deepseek};anthropic 只接受 `api_key`(PUT `subscription` → 400);GET 响应**不含** `platform_default`/`platform_auth_type`;minimax/deepseek 写入落 `MINIMAX_*`/`DEEPSEEK_*`;删 gemini 相关用例;删 platform-default 用例。
- [ ] **Step 2: 跑测试确认失败。**
- [ ] **Step 3: 实现** — `_PROVIDERS` 按 design §1;删 `_platform_default_auth`;`_provider_status` 去两字段(二态)。
- [ ] **Step 4: 跑测试确认绿。**
- [ ] **Step 5: 提交** `feat(9a/providers): model-config providers = anthropic(api-key)/openai/minimax/deepseek, drop platform-default+gemini`

---

## Task 4: 默认智能体 4→5(加 deepseek,minimax/deepseek 走新 harness)

**Files:** Modify `services/gateway/bff/omnigent_proxy.py`;Test `tests/gateway/bff/test_agents.py`

- [ ] **Step 1: 改 `test_default_enterprise_agent_templates_are_fixed_four`** → 五个:`["minimax","deepseek","debby","codex","polly"]`;断言 `minimax.harness=="minimax"`、`deepseek.harness=="deepseek"`、`deepseek.model=="deepseek-chat"`(按 Task 1)。
- [ ] **Step 2: 跑测试确认失败。**
- [ ] **Step 3: 实现** — `DEFAULT_ENTERPRISE_AGENTS` 加 deepseek 模板、minimax 改 `harness="minimax"`。
- [ ] **Step 4: 跑 default-agents/ensure 全组测试确认绿(补种/幂等/不覆盖仍成立)。**
- [ ] **Step 5: 提交** `feat(9a/providers): default agents 4->5 (add deepseek; minimax/deepseek use own harness)`

---

## Task 5: compose/config env 槽 + 去平台 claude 全局回退

**Files:** Modify `deploy/dev/omnigent/config.yaml`、`deploy/dev/omnigent/docker-compose.yml`

- [ ] **Step 1: `config.yaml` `sandbox.docker.env`** 按 design §4:加 `MINIMAX_*`/`DEEPSEEK_*`(+ 按 Task 1 的 `HARNESS_*_MODEL`),去 `CLAUDE_CODE_OAUTH_TOKEN`/`GEMINI_API_KEY`。
- [ ] **Step 2: `docker-compose.yml`** 删全局 `CLAUDE_CODE_OAUTH_TOKEN: ${...:?}` 注入;保留 `secrets/model-config` 只读挂载。
- [ ] **Step 3: `bash -n` / compose config 校验语法。**
- [ ] **Step 4: 提交** `chore(9a/providers): sandbox env slots for minimax/deepseek; drop global claude subscription fallback`

---

## Task 6: 前端(provider 列表、去平台默认 UI、anthropic 仅 api key)

**Files:** Modify `frontend/src/api/modelConfig.ts`、`frontend/src/pages/ModelConfig.tsx`、`ModelConfig.test.tsx`、`modelConfig.test.ts`

- [ ] **Step 1: 改测试** — `PROVIDERS` = 四项无 gemini;anthropic 只 `api_key`;渲染无"平台默认"徽标;minimax/deepseek 卡片出现 + base_url 输入。
- [ ] **Step 2: 跑测试确认失败。**
- [ ] **Step 3: 实现** — `PROVIDERS` 表更新;`ProviderStatus` 去两字段;`ModelConfig.tsx` 删 `platformDefault` 分支(徽标/覆盖文案),二态渲染。
- [ ] **Step 4: `npx vitest run` 相关文件确认绿。**
- [ ] **Step 5: 提交** `feat(9a/providers): model-config UI — 4 providers, drop platform-default, anthropic api-key only`

---

## Task 7: ADR-028 + runbook + 迁移说明

**Files:** Create `docs/adr/ADR-028-per-enterprise-model-credentials.md`;Modify `docs/superpowers/plans/2026-06-28-omnigent-integration/RUNBOOK.md`

- [ ] **Step 1: 补 ADR-028** — 记 as-built(每企业凭据文件注入、labels.enterprise_id 命门)+ 本次增量(provider 集合、每 provider 独立 harness/槽、去 anthropic 平台默认+订阅、默认 agent 5 个)。
- [ ] **Step 2: runbook** — 更新模型配置验收:配 anthropic/minimax/deepseek 三凭据 → 分别用对应默认 agent 各跑一轮;显式写"去平台 claude 回退后需先配 ANTHROPIC_API_KEY 否则 claude agent 不可用"。
- [ ] **Step 3: 提交** `docs(9a/providers): ADR-028 + runbook (per-provider harness, drop platform default)`

---

## Final Verification
- [ ] `uv run pytest tests/gateway/bff/test_model_config.py tests/gateway/bff/test_agents.py -q`
- [ ] fork 侧 harness 单测绿
- [ ] `cd frontend && npx vitest run src/pages/ModelConfig.test.tsx src/api/modelConfig.test.ts src/pages/Agents.test.tsx`
- [ ] `make test`(全量绿)+ `make lint`(护栏 + 分层绿)
- [ ] `docker compose -f deploy/dev/omnigent/docker-compose.yml config`(compose 语法)

## Manual Acceptance Runbook(面向 owner,大白话)
1. `make ws-up` → 你应看到 5 个默认 agent(minimax、deepseek、debby、codex、polly)created/skipped 摘要。
2. 打开「模型配置」页 → 你应看到 **4 个 provider:Anthropic (Claude)、OpenAI (Codex)、MiniMax、DeepSeek**,**没有 Gemini**,Anthropic **没有"平台默认"徽标、只有 API key**。
3. 给 MiniMax、DeepSeek 分别配 key + endpoint(dev 测试凭据)→ 两者都显示"本企业已配置"。
4. 用 minimax、deepseek 两个默认 agent 各发一条消息 → 都能流式回复,后台看两者读的是不同槽的凭据(不串号)。
5. **不配 Anthropic** 时用 debby 对话 → 明确报 anthropic 未配置/agent 不可用;配上 `ANTHROPIC_API_KEY` 后再试 → 可用。
6. 只配 MiniMax、不配 DeepSeek → 用 deepseek agent → 明确不可用,**不**误用 MiniMax 的 key。

## Self-Review
- [ ] 四组 env 槽命名互不重叠(不串号)。
- [ ] Anthropic 去平台默认 + 去订阅,二态渲染。
- [ ] 去平台 claude 回退的迁移影响已在 runbook/PR 显式告知。
- [ ] fork harness 复制以 Task 1 实测为准,无猜写。
- [ ] 授权/隔离/字面值红线未被破坏。
