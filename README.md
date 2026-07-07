# lite-ai-infra

多企业（multi-enterprise）SaaS 形态的 LLM 基础设施平台。已可在本地 Mac 一键起全栈：**统一登录（Keycloak）→ 控制台 → Workspace 里和 AI agent 对话**，每企业自管模型凭据（Anthropic / OpenAI / MiniMax / DeepSeek），身份/授权/审计/隔离全链路打通。

> 架构宪法（必读、不可违反）：[`docs/constitution.md`](docs/constitution.md)
> 详细设计：[`docs/superpowers/specs/2026-05-08-llm-infra-platform-design.md`](docs/superpowers/specs/2026-05-08-llm-infra-platform-design.md)
> 手动验收 runbook（照着点，不用读代码）：[`docs/superpowers/plans/2026-06-28-omnigent-integration/RUNBOOK.md`](docs/superpowers/plans/2026-06-28-omnigent-integration/RUNBOOK.md)

---

## 🚀 快速开始（一键起全栈）

### 0. 前置依赖

| 工具 | 用途 | 安装 |
|---|---|---|
| **uv** ≥ 0.9 | Python 环境/依赖（环境即工程，宪法 §5.8）| `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| **Docker Desktop**（arm64，需能跑 docker CLI + 挂 docker.sock）| Keycloak / MinIO / omnigent 沙箱 | https://docker.com |
| **Node.js** ≥ 18（含 npm）| 前端构建（Vite）| https://nodejs.org |
| `git` | 拉子模块（omnigent fork）| — |

- **Python 不用手动装**：基线钉在 `.python-version`=`3.12`，`uv` 会自动获取 CPython 3.12 并建独立 `.venv`；命令一律走 `uv run` / `make`。
- **要空闲的端口**：**8090**（控制台入口）、**8080**（Keycloak）、**9000/9001**（MinIO）、**8900**（omnigent）。见下方「排错」。
- **拉子模块**（omnigent 是我们的 fork，作 git submodule）：`git submodule update --init third_party/omnigent`

### 1. 一次性初始化

```bash
git submodule update --init third_party/omnigent   # 拉 omnigent fork（首次）
make sync                                           # 建/同步 .venv(3.12) 并装 Python 依赖
make fe-install                                     # 装前端依赖（frontend/node_modules；ws-up build 前端需要）
```

### 2. 一键起全栈

```bash
make ws-up       # 起 Keycloak+MinIO → 置备用户/企业 → 自编译并起 omnigent(server+host) → build 前端 → 起网关(8090)
```

`ws-up` 会按依赖顺序把整套起齐并逐个等就绪（首次要拉/编译镜像，稍慢）。末尾打印**唯一入口**：

```
┌─ 唯一入口（浏览器开这个）───────────────────────────┐
│  http://localhost:8090   控制台 + 登录 + Workspace，同源 │
└──────────────────────────────────────────────────────┘
```

### 3. 登录 + 配模型 + 对话

1. 浏览器开 **http://localhost:8090** → 未登录会跳 Keycloak，用 **`alice`/`alice`**（企业管理员）或 **`bob`/`bob`**（普通成员）登录。两人同属企业 `ent-demo`。
2. **先配模型凭据**（否则 agent 起不来）：管理员 `alice` 进左侧 **「模型配置」** → 给要用的 provider 填 key/endpoint（见下方 §模型配置）。
3. 进 **Workspace** → 新建会话 → 选一个默认智能体发消息，回复会流式冒出来。默认智能体：**minimax、deepseek、debby、codex、polly**。

### 4. 停全栈

```bash
make ws-down     # 停所有服务 + omnigent + 清理动态拉起的 managed 沙箱容器（Keycloak/MinIO 数据保留）
```

---

## 🔑 模型配置（让 agent 能调模型）

模型凭据**每企业各配**，由企业管理员在控制台「模型配置」页填写（ADR-028）。四个 provider：

| Provider | 凭据类型 | 说明 |
|---|---|---|
| **Anthropic (Claude)** | 仅 API key | 驱动 `debby`/`polly`（claude-sdk）；**未配则这些 agent 不可用**（平台不再自带 claude 订阅）|
| **OpenAI (Codex)** | API key / 订阅 | 真 OpenAI / Codex |
| **MiniMax** | API key（+ base_url）| OpenAI 兼容；驱动 `minimax` 默认 agent，独立凭据槽 |
| **DeepSeek** | API key（+ base_url）| OpenAI 兼容；驱动 `deepseek` 默认 agent，独立凭据槽 |

- 值落 **gitignored** 文件 `secrets/model-config/<企业alias>.json`（env 名→字面值），omnigent 只读挂载、按会话企业注入沙箱。**绝不进代码仓、绝不回显**。
- MiniMax、DeepSeek 各有独立槽（`MINIMAX_*` / `DEEPSEEK_*`），**可同时配、互不串号**。
- 命令行补种默认 agent（dev/ops）：`make provision-default-agents EID=ent-demo`

---

## 🛠 调试 / 排错

### 看日志

各 uvicorn 服务日志在 `.dev/`（`ws-up` 后台起的）：
```bash
tail -f .dev/gateway.log        # 网关（BFF，含 omnigent 反代、model-config、agent 库）
tail -f .dev/frontend.log       # 前端 build
tail -f .dev/identity.log       # identity-org
```
容器（Keycloak / MinIO / omnigent）日志：
```bash
docker compose -f deploy/dev/omnigent/docker-compose.yml logs -f omnigent
docker compose -f deploy/dev/docker-compose.yml logs -f keycloak
docker ps --filter name=omnigent-managed-        # 每个活跃用户/会话一个隔离沙箱容器
```

### 改了 omnigent（fork）代码 → 重编译生效

omnigent 是我们的 fork（`third_party/omnigent`，作 submodule）。改完重编译 + 重起：
```bash
scripts/omnigent_build.sh dev                                      # 自编译 server+host:dev 镜像
docker compose -f deploy/dev/omnigent/docker-compose.yml up -d --force-recreate omnigent
```
> 若 docker build 里报 DNS/网络错（沙箱拦了外网），在允许联网的终端里跑该命令。

### 改了前端 → 重 build

前端由网关在 8090 同源发出（非 vite 5173，热更新延后）：
```bash
make fe-build     # 重 build frontend/dist，网关自动发新版
```

### agent 起不来 / 回复报「不可用」

多半是**模型凭据没配**：去「模型配置」把对应 provider 配好（claude 类 agent 需本企业 `ANTHROPIC_API_KEY`）。

### 端口被占（`address already in use`）

```bash
lsof -nP -iTCP:8090 -sTCP:LISTEN     # 换 8080/9000/9001/8900 逐个查
```
停掉占用进程，或 `make ws-down` 清干净再起。

### `uv run pytest` 找不到模块

先 `make sync` 建好 `.venv`；在**仓库根目录**运行（`pyproject.toml` 设了 `pythonpath=["."]`）。

### Keycloak 取 token 报 `Account is not fully set up`

种子用户缺 `firstName`/`lastName`/`emailVerified`（KC 26 声明式 profile 校验）——`realm-lite-ai.json` 已修；自建用户需补齐这三项。

---

## 🧪 开发与测试

| 命令 | 作用 | 期望 |
|---|---|---|
| `make test` | 后端单元测试（零依赖，`-m "not integration"`）| `324 passed` |
| `make lint` | 分层检查（import-linter）+ 宪法 §8 grep 护栏 | `layering KEPT` + `0 broken` |
| `make gen` | OpenAPI 契约 → Pydantic 模型代码生成（确定性）| 更新 `libs/contracts_gen/*` |
| `make fe-test` | 前端单测（vitest）| all passed |
| `make test-integration` | 集成测试（需先起依赖）| 见 §集成 |

跑单个测试 / fork 测试：
```bash
uv run pytest tests/gateway/bff/test_model_config.py -q               # 单文件
uv run pytest tests/authz/test_can.py::test_can_v1_matrix -q          # 单用例
(cd third_party/omnigent && ./.venv/bin/python -m pytest tests/inner/test_provider_harnesses.py -q)  # fork 单测
```
> 直接敲裸 `pytest`/`lint-imports` 会找不到命令——它们在 uv 管理的 `.venv` 里，必须 `uv run <cmd>` 或 `make <target>`。

### 单独起某个微服务（前台 + 热重载）

架构 = 真微服务，各独立 uvicorn，gateway 应用内 httpx 反代：

| 服务 | 端口 | 启动 |
|---|---|---|
| api-gateway（BFF / 反代壳）| **8090** | `make run-gateway` |
| identity-org-service | 8001 | `make run-identity` |
| metadata-service | 8002 | `make run-metadata` |
| data-pipeline-service | 8003 | `make run-data-pipeline` |
| omnigent（server）| 8900 | `make omnigent-up` |

`make up` / `make ps` / `make down` 起停/查看 deps + 基础服务进程（不含 omnigent/前端，全栈用 `ws-up`）。

**看 API 文档**：`make api-docs` → http://localhost:8088（聚合全部契约）；或运行时每服务自带 `/docs`（如 `:8090/docs`）。

---

## 🔐 dev Keycloak realm（`lite-ai`）

`make ws-up` 内已起并置备。手动看：Admin Console http://localhost:8080/admin（`admin`/`admin`）。

- 企业 = KC Organization（ADR-025）；dev 企业 `ent-demo`，种子用户 `alice`（enterprise-admin）、`bob`（member）。
- client `lite-ai-web`（授权码 + PKCE，BFF 登录专用）、client `gateway`（ROPC，仅集成测试/ops 取 token）。

> **🔴 prod 硬门**：`lite-ai-web` secret 走 secret 管理（非 dev 值）；回调用 prod 域名；`gateway` 关 ROPC；会话 cookie `Secure`。dev 用固定 dev 值。

集成测试（真 Keycloak/MinIO）：`make dev-up && make test-integration`。

---

## 📁 代码结构

```
lite-ai-infra/
├── contracts/openapi/*.yaml       # API 契约（API-first 真相源）
├── libs/
│   ├── identity/                  # KC token → 带 scope 的 Context
│   ├── authz/{types,engine}.py    # Resource/Decision + can()：唯一授权出入口（宪法 §2.4）
│   ├── audit/oss_audit.py         # 追加写审计（ADR-010）
│   └── contracts_gen/             # 契约生成的 Pydantic 模型（make gen 产物）
├── services/
│   ├── gateway/                   # 网关/BFF：登录、反代 omnigent、模型配置、智能体库
│   ├── identity_org_service/      # 企业/成员
│   ├── metadata_service/          # 数据集元数据
│   └── data_pipeline_service/     # 数据管线
├── frontend/                      # 控制台（TypeScript + Vite；网关同源发 dist）
├── third_party/omnigent/          # 我们 fork 的 omnigent（submodule，自编译镜像）
├── deploy/dev/                    # docker-compose（Keycloak/MinIO）+ omnigent compose + seeded realm
├── scripts/                       # ws_up/ws_down、omnigent_build、provision_* 等
├── secrets/model-config/          # 每企业模型凭据（gitignored）
└── tests/                         # 后端单元（零依赖）+ integration/
```

分层纪律（宪法 §4.1，import-linter 强制）：`services → libs` 单向，`libs` 不得反向 import `services`。

---

## 🌐 环境矩阵

| 环境 | 位置 | 身份 | 对象存储 | agent 后端 |
|---|---|---|---|---|
| dev | 本地 Mac（docker-compose）| Keycloak 26.6.2 容器 | MinIO（S3 兼容）| omnigent 自编译 :dev |
| test | 阿里云 ACK | ACK 上 Keycloak | 阿里云 OSS | omnigent CI 发布镜像 |
| CI | GitHub Actions | 容器 Keycloak | 容器 MinIO | — |

CI 用 `astral-sh/setup-uv` + `uv sync` + `uv run` 复现同一 3.12 环境，跑单元 + lint + §8 护栏 + 契约 breaking（oasdiff）+ codegen 新鲜度。
