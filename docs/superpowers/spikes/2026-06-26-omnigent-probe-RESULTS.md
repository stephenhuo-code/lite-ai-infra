# Task 0 探针 RESULTS — omnigent 实跑(Plan 9 受控链路承重墙)

> 状态:**进行中**。日期 2026-06-26。镜像 `ghcr.io/omnigent-ai/omnigent-server:latest`(digest `sha256:112be2e5f8d1eae47edbd3892243a47bfde2b3a462f0a6a595f15ac4207aed1b`,**linux/arm64 原生**)。
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

## 待完成(承重墙 ② + 沙箱)

### Step 3–4 — 承重墙 ②(令牌随 URL 抵达我们的工具)⏳
需要:① 起最小令牌化 MCP server(`/s/<token>/mcp`)② 注册一个 host/runner ③ 用 `hello_world.yaml` 建 agent + 会话 ④ 注册我们的 MCP server(http,令牌 URL)⑤ 触发 runner 预热/turn → 看我们的服务是否收到带 `<token>` 的连接。
- **决策规则**:若 omnigent 按注册 URL 原样连(令牌到达)→ ② 成立,Task 2–6 照写。若 URL 被改写/丢令牌 → 触发 design 备选(查 header/env 转发槽;无则改 stdio + 令牌走 args)。

### Step 5 — 沙箱限工作目录 ⏳
- 本地沙箱实现已知(源码):Linux=bwrap / macOS=seatbelt / Win=jobobject;cwd 默认只读、`write_paths` 显式授权、`$HOME` 不挂载、网络按地址族过滤。配置 = 每会话/环境 `OSEnvSandboxSpec(write_paths/read_paths/allow_network)`。
- 待实跑:让 agent 越界写 → 应被拒;并记录 environment 工作目录路径(9d 持久化要用)。

## 待钉版本
- 采用后把 `:latest` 换实测 `:vX.Y.Z`(当前 digest 已记于顶部)。
