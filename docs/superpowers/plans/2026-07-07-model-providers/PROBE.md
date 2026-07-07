# PROBE(探针实测):每 provider 独立 harness(2026-07-07)

> 目的:用真实代码/真链路确认 design §3.3/§4 的未知,把事实写死,后续实现以此为准(禁猜)。
> 探针载体:直接改 `third_party/omnigent`(minimax harness + 登记)+ 结构验证 + 真链路一轮。

## 结论速览
复制 openai-agents 得到一个可运行的 `minimax` harness,真链路(managed docker 沙箱)**跑通一轮**,流式返回 MiniMax 真实回复。
每新增一个 provider harness 需改 **fork 的 6 处** + Lite-AI 的 config/compose。design 原先只列了 2–3 处,**漏了第 5、6 处(spec 校验允许集 + host→runner 凭据转发白名单)**——本探针补上。

## 每新增一个 provider harness 要改的 6 处(fork)
1. **新 harness 模块** `omnigent/inner/<provider>_harness.py`(`create_app()` 复用 `OpenAIAgentsSDKExecutor`,读自己的槽)。
2. **harness 注册** `omnigent/runtime/harnesses/__init__.py::_HARNESS_MODULES`(runner 据此 import+调 `create_app()`)。
3. **model override 允许集** `omnigent/model_override.py::_SDK_MODEL_OVERRIDE_HARNESSES`(否则 model 覆盖不落 spawn env)。
4. **model→env 键映射** `omnigent/runner/app.py::_HARNESS_MODEL_ENV_KEY`(**硬编字典**;agent spec 的 `model` 到达 harness 的唯一通道)。
5. **spec 校验允许集** `omnigent/spec/_omnigent_compat.py::OMNIGENT_HARNESSES`(否则 POST /v1/agents 返回 `400 executor.config.harness: must be one of [...]`)。← 探针实测发现
6. **host→runner 凭据转发白名单** `omnigent/host/connect.py::HARNESS_CREDENTIAL_ENV_VARS`(加 `MINIMAX_*`/`DEEPSEEK_*`;否则注入 host 也到不了 runner)。← 探针实测发现

## (原“4 处 fork 登记”明细,保留供参考)
1. **harness 注册** `omnigent/runtime/harnesses/__init__.py::_HARNESS_MODULES`
   `"minimax": "omnigent.inner.minimax_harness"`。runner 据此 import 模块、调 `create_app()`。
2. **model override 允许集** `omnigent/model_override.py::_SDK_MODEL_OVERRIDE_HARNESSES`
   加 `"minimax"`,否则该 harness 的 `model` 覆盖不会落进 spawn env。
3. **model→env 键映射** `omnigent/runner/app.py::_HARNESS_MODEL_ENV_KEY`(**硬编码字典,非通用派生**)
   `"minimax": "HARNESS_MINIMAX_MODEL"`。这是 agent spec 的 `model` 到达 harness 的唯一通道。
4. **host→runner 凭据转发白名单** `omnigent/host/connect.py::HARNESS_CREDENTIAL_ENV_VARS`
   含 `OPENAI_API_KEY/OPENAI_BASE_URL/ANTHROPIC_*/GEMINI_API_KEY/CODEX_ACCESS_TOKEN`,**不含 `MINIMAX_*`/`DEEPSEEK_*`**。
   新凭据 env 名必须加进此集合(一等公民),否则注入到 host 也**到不了 runner**,harness 读不到 key。
   探针期临时用 compose `OMNIGENT_RUNNER_ENV_PASSTHROUGH=...,MINIMAX_API_KEY,MINIMAX_BASE_URL` 等价转发(免再 rebuild)。

## config / compose(Lite-AI 侧)
- `deploy/dev/omnigent/config.yaml` `sandbox.docker.env`:加 `MINIMAX_API_KEY`/`MINIMAX_BASE_URL`(把 host 注入的凭据名列出;值按企业文件 `<alias>.json` 解析)。
- 上游 `cli.py::_LOCAL_DAEMON_ENV_ALLOWLIST` **不管**我们的 docker 受管注入路径(它只在 cli 本地 daemon 路径 `cli.py:2300` 被引用;`onboarding/sandboxes/docker.py::_resolve_sandbox_env` 不引用它)。→ **design §4 那条"须改上游白名单"可撤**。

## harness 实现要点(实测/读码确认)
- harness 在 **runner 进程内**跑(`create_app()` 返回 FastAPI app,由 `ExecutorAdapter` 建),所以只要 `MINIMAX_API_KEY` 在 runner env 里,`os.environ` 直接可读。
- 复用 `OpenAIAgentsSDKExecutor`;显式传 `api_key`(胜过 ambient `OPENAI_API_KEY`)+ `base_url_override`。
- `use_responses=False`(MiniMax/DeepSeek 只讲 `/chat/completions`,SDK 默认 `/responses` 会 404)。
- `base_url`/`model` 缺失时用 provider 默认常量(避免误路由到 api.openai.com):MiniMax = `https://api.minimaxi.com/v1` / `MiniMax-Text-01`。
- `canonicalize_harness("minimax")` 透传为 `"minimax"`;`model_family_mismatch("minimax", "MiniMax-Text-01")` = None(多模型 harness,不被家族门拒)。

## 结构验证(fork .venv,真实执行,已通过)
```
1) _HARNESS_MODULES[minimax] OK
2) create_app() OK -> FastAPI
3) model-override registries OK (_SDK_MODEL_OVERRIDE_HARNESSES + _HARNESS_MODEL_ENV_KEY[minimax]=HARNESS_MINIMAX_MODEL)
4) executor built -> OpenAIAgentsSDKExecutor (读 MINIMAX_* 槽)
5a) canonicalize(minimax) -> 'minimax'
5b) family_mismatch -> None
ALL PROBE CHECKS PASSED
```

## 真链路一轮(managed docker 沙箱)—— 通过
- 载体:`make ws-up` 起全栈;`secrets/model-config/ent-demo.json` 加 `MINIMAX_API_KEY`/`MINIMAX_BASE_URL`(= 现有 OPENAI_* 值,即可用 MiniMax 凭据);`config.yaml` 加 `MINIMAX_*` 注入;compose `OMNIGENT_RUNNER_ENV_PASSTHROUGH` 加 `MINIMAX_API_KEY,MINIMAX_BASE_URL`;重建镜像 + 重启 omnigent;建 `harness=minimax` 的 agent 发一条消息。
- 证据(SSE 流):
  - `CREATE agent: 200 ... "harness":"minimax"`
  - `CREATE session: 201 ... "labels":{"enterprise_id":"ent-demo"},"runner_online":true`
  - `POST turn: 202 {"queued":true}`
  - `response.output_text.delta` 增量:`你好` / `，我是一个由人工智能驱动的助手，旨在帮助您解决问题并提供信息。` → `response.output_item.done`(status completed)
- 结论:minimax harness 读 `MINIMAX_*` 槽,凭据链 `企业文件→host 注入→runner 转发→harness` 完整走通,真实调用 MiniMax 并流式回复。**与 openai-agents 的 `OPENAI_*` 槽互不冲突**(两槽独立)。

## 对 design/plan 的修订(据探针)
- design §3.3/§4 的 `待探针` 项 → 已决定:model-flow 走 `_HARNESS_MODEL_ENV_KEY`(硬编字典,需登记);use_responses=False;endpoint 默认常量。
- **新增第 4 处 fork 改动**:`host/connect.py::HARNESS_CREDENTIAL_ENV_VARS` 加 `MINIMAX_*`/`DEEPSEEK_*`。plan Task 2 增此步。
- 撤销 design §4 的"改上游 `cli.py` env 白名单"(不在受管注入路径上)。
