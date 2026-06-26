# Task 0 探针 RESULTS — omnigent 实跑(Plan 9 受控链路承重墙)

> 状态:**完成 ✅ 两承重墙均通过**。日期 2026-06-26。镜像 `ghcr.io/omnigent-ai/omnigent-server:latest`(digest `sha256:112be2e5f8d1eae47edbd3892243a47bfde2b3a462f0a6a595f15ac4207aed1b`,**linux/arm64 原生**)。
>
> **终判:omnigent 可用,design 的受控链路核心成立。Task 1–6 照写。**
> 探针 compose:`deploy/dev/omnigent.yml`(postgres + omnigent header 模式 + `/data` 卷,对外 8900)。

## 已确认(✅)

### Step 1 — boot ✅
- omnigent server **健康起来**(postgres healthy → omnigent healthy)。镜像 arm64 原生(无模拟);postgres:16-alpine 为 amd64(模拟,可用)。
- 健康端点 **`/healthz` 存在(200)**;`/`(200)。→ 决策:健康探针用 `/healthz`。
- 必填依赖(实测):postgres + `DATABASE_URL`;`ARTIFACT_DIR=/data/artifacts`;`OMNIGENT_ADMIN_CREDENTIALS_PATH=/data/admin-credentials`(需持久卷)。唯一必填 secret = `POSTGRES_PASSWORD`。

### Step 2 — header-auth ✅(承重墙 ①)
- `OMNIGENT_AUTH_PROVIDER=header` + `OMNIGENT_AUTH_HEADER=X-Forwarded-Email`,**纯 env,零改码**。
- **缺头 → 401**;**带头 `X-Forwarded-Email: alice@acme.test` → 200**(返回会话列表)。→ **承重墙 ① 成立**:BFF 注入身份头即可,OIDC 非必需。design 假设确认。

### 真实执行模型(探针逼出的关键事实)⚠️
- **裸 server 不能执行 agent**:`GET /v1/agents` 空、`GET /v1/runners` 空。
- 建会话 `POST /v1/sessions` **required `agent_id`**(空 body → 422 missing agent_id)。
- 执行需三件套:**① host/runner**(`omnigent host <url>` 把机器注册为 host,或跑 `omnigent-host` 镜像;`POST /v1/hosts/{id}/runners`)**② agent spec**(YAML,repo 有 `tests/resources/examples/hello_world.yaml`;CLI 有 `default_agent` 概念)**③ 模型凭证**。
- → **对 design 的影响**:我们的部署除 server 外**还要部署 host/runner**(本地沙箱后端);"两套后端并存"成本比预想多一个 host 组件。**记入 design/ADR-026 运维成本**。

### 模型凭证(实测路径)
- claude harness 支持 **Claude 订阅**:`claude setup-token` → 存 `CLAUDE_CODE_OAUTH_TOKEN`(长效);或 `ANTHROPIC_API_KEY`。→ 可复用 owner 的订阅,无需单独买 API。

### MCP 连接时机(利于低成本验②)
- `omnigent/runner/mcp_manager.py`:有 **prewarm/`_connect_all`/`needs_connect`** —— runner **预热时即连接 MCP server 列工具**,非"仅 turn 中调用"。→ **注册令牌化 MCP server 后,runner 预热就会连我们的服务**,可能**不烧模型 token 即验到"令牌随 URL 抵达"**(承重墙 ②)。

### Step 3–4 — 承重墙 ②(令牌随 URL 抵达我们的工具)✅ **确认**
实跑方式(比计划更简洁):用 `omnigent run <agent.yaml>` 本地 runner + **claude-native harness(吃 owner Claude 订阅,`CLAUDE_CODE_OAUTH_TOKEN`)**,agent spec 里 `tools.liteai: {type: mcp, transport: http, url: http://localhost:8901/s/probe-tok-abc/mcp}`;我们起最小 FastMCP `streamable_http_app()` + 令牌路由包裹(`/s/<token>/mcp` → 提取令牌入 contextvar)。
- **结果(我们 MCP server 日志)**:
  ```
  [liteai-mcp] HIT path=/s/probe-tok-abc/mcp token=probe-tok-abc
  POST /s/probe-tok-abc/mcp -> 200 (initialize)
  POST /s/probe-tok-abc/mcp -> 202 (notifications/initialized)
  POST /s/probe-tok-abc/mcp -> 200 (ListToolsRequest)
  ```
- **结论**:omnigent runner **按注册 URL 原样连接**,**令牌 `probe-tok-abc` 随 URL 完整抵达我们的服务**,并完成 initialize + **list_tools**。→ **承重墙 ② 成立**:令牌绑定机制端到端跑通,我们的 MCP server(can() 所在)在每次工具交互中都在环路里。决策规则命中"原样连"分支 → Task 2–6 照写,**无需** header-带令牌 / stdio 备选。
- **关键实现事实(Task 3/4 用)**:
  - mcp SDK `FastMCP.streamable_http_app()` **存在可用**;令牌走 URL 路径前缀 + ASGI 包裹剥离 **可行**(已实跑)。
  - **工具命名 = `{server_name}__{bare_name}`**(`omnigent/runner/mcp_manager.py:141`)→ 我们的工具对 agent 显示为 **`liteai__ping`**(本次 agent 搜 "ping" 没匹配上 = 命名,非故障;omnigent 已成功列举)。**Task 3/4 工具命名/提示词需用带前缀名**。
  - claude-native 把所有 omnigent 工具经**一个 stdio 桥**汇入 Claude Code(`claude_native_bridge.py:989`),runner 自己连我们的 http MCP —— 与 design 一致。
  - **spec 形态**:`omnigent run` 用**扁平** `executor.harness: claude-native`(非嵌套 `executor.config.harness`,后者是 polly 子 agent 形态)。

### Step 5 — 沙箱限工作目录:**源码确认 + 实跑待 Task 3/4 集成**
- 源码确认:本地沙箱 Linux=bwrap / macOS=seatbelt / Win=jobobject;cwd 默认只读、`write_paths` 显式授权、`$HOME` 不挂载、网络按地址族过滤;配置 = 每会话/环境 `OSEnvSandboxSpec(write_paths/read_paths/allow_network)`(`inner/datamodel.py`)。本次探针 agent 用 `os_env.sandbox.type: none`(为隔离测②变量)。
- **非承重墙**(沙箱是 omnigent 核心能力,源码清晰)→ **live 越界写测试挪到 Task 3/4 集成**(届时设 `sandbox` + 限 `write_paths` 到 workspace 目录,跑越界写应被拒;并记 environment 工作目录路径供 9d)。

## 对 design / 计划的影响(回写)
1. **新增运维组件**:除 omnigent server,**还需部署 host/runner**(本地沙箱后端)——"两套后端并存"实为 server + host/runner。**已记**,Task 1 部署固化含此。
2. 承重墙②走 `omnigent run` 本地 runner 即可验,正式集成走 server + host + session API(Task 5)。
3. 模型凭证:claude-native 吃 `CLAUDE_CODE_OAUTH_TOKEN`(owner 订阅)→ secret 注入,§5.2。

## 待钉版本
- 采用后把 `:latest` 换实测 `:vX.Y.Z`(当前 digest 已记于顶部);自构建固化见 9-prod。

---
## 9b + 9d 探针(2026-06-26,源码级解掉,无需 live)

> 来源:omnigent 官方客户端 `ap-web/src/lib/{sessionsApi,types,sse}.ts` + openapi `ServerStreamEvent`。
> 官方客户端做的正是我们 9b 要做的 → 直接采信,无需起 omnigent + host + 模型 token。

### 9b① 发 user turn = `POST /v1/sessions/{id}/events`(承重墙解)
body = `SessionEventInput`(= `omnigent.server.schemas.SessionEventInput`):
```json
{ "type": "message",
  "data": { "role": "user",
            "content": [ { "type": "input_text", "text": "<用户消息>" } ] } }
```
- 其它事件同端点:`{type:"interrupt"}`、`{type:"stop_session"}`、`{type:"approval"}`、`{type:"function_call_output"}`。
- 响应 `PostEventResponse` = `{queued, item_id?, denied?, pending_id?}`。
- **runner 未连 → 503**(再证需 host/runner)。

### 9b② stream = `GET /v1/sessions/{id}/stream`(SSE,非 WS)
- `Accept: text/event-stream`,body 是 SSE,逐条 `ServerStreamEvent`(openapi 联合)。
- **BFF 决策:SSE 透传(StreamingResponse),非 WS 反代** → 9b Task 2 据此实现。
- 前端消费事件(openapi 事件类型 + ap-web):
  - `response.output_text.delta`(`OutputTextDeltaEvent`)→ 流式 assistant 文本气泡
  - `response.output_item.done`(`OutputItemDoneEvent`)→ 工具调用/结果卡
  - `ElicitationRequestEvent` / `response.elicitation.*` → **ASK 审批卡**
  - `ReasoningTextDeltaEvent` → 思考流;`response.created/completed/incomplete`、`ErrorEvent`、`HeartbeatEvent` → turn 生命周期
  - item 形态:`{type:"message", role, content:[{type:"output_text", text}]}` / `{type:"user_message"}`

### 9b③ ASK 审批 = `POST /v1/sessions/{id}/elicitations/{eid}/resolve`
- body = MCP `ElicitResult`;elicitation id 在 URL,非 body。对应原型的 ASK 审批卡"批准/拒绝"。

### 9d filesystem(同步形态解)= environment filesystem API
- 读 `GET …/environments/{eid}/filesystem/{relative_path}` → `{content, encoding}`(utf-8 / base64,见 ap-web `useFileContent`)。
- 写 `PUT …/filesystem/{relative_path}` body `{content, encoding}`(见 `useWriteFileContent`)。删 `DELETE`;变更 `GET …/changes`。
- **9d 决策:同步走"遍历 filesystem API 读写"**(plan 9d Task0 决策规则的 ②分支);workspace_store 真实 syncer 据此实现(OSS ↔ filesystem API)。

### 结论
**9b Task 0 与 9d Task 0 均解(源码级)。** 解锁:9b Task 2(SSE 透传反代)/ Task 5(对话流消费)/ Task 6(文件 GET-PUT、终端 WS)/ Task 7;9d 真实 syncer。**未起 live**(契约取自官方客户端,权威);如需 end-to-end live 确认,按地基 RUNBOOK B 跑一次即可。
