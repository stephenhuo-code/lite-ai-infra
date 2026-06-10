# lite-ai-infra

多企业（multi-enterprise）SaaS 形态的 LLM 基础设施平台。当前处于 **S0 地基**阶段：身份解析（Keycloak token → 带 scope 的 `Context`）、统一授权出入口 `can()`、追加写审计、API 契约 + 代码生成，全部可在本地 Mac 上开发与测试。

> 架构宪法（必读、不可违反）：[`docs/constitution.md`](docs/constitution.md)
> 详细设计：[`docs/superpowers/specs/2026-05-08-llm-infra-platform-design.md`](docs/superpowers/specs/2026-05-08-llm-infra-platform-design.md)
> S0 实现计划与验收 runbook：[`docs/superpowers/plans/2026-06-08-s0-foundation.md`](docs/superpowers/plans/2026-06-08-s0-foundation.md)

---

## 1. 前置依赖

| 工具 | 用途 | 安装 |
|---|---|---|
| **uv** ≥ 0.9 | Python 环境/依赖管理（环境即工程，宪法 §5.8）| `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| **Docker Desktop**（arm64）| 本地跑 Keycloak + MinIO | https://docker.com |
| `git` | —  | — |

- **Python 解释器不需要手动装**：基线钉在 `.python-version` = `3.12`，`uv` 会按需自动获取 CPython 3.12 并建独立 `.venv`。系统自带的 python（如 3.9）不参与，命令一律走 `uv run`。
- **端口要求**：dev 环境占用 **8080**（Keycloak）、**9000/9001**（MinIO）。运行前确保这三个端口空闲（见 §7 排错）。

---

## 2. 一次性初始化

```bash
make sync        # = uv sync --extra dev ：按 uv.lock 建/同步 .venv(3.12) 并装依赖（含 dev 工具）
```

完成后即可离线复现同一环境（dev / CI / 阿里云三处一致：`.python-version` + `uv.lock`）。

---

## 3. 日常开发命令（全部经 `make` / `uv run`）

| 命令 | 作用 | 期望 |
|---|---|---|
| `make test` | 单元测试（零依赖，默认 `-m "not integration"`）| `23 passed` |
| `make lint` | 分层检查（import-linter）+ 宪法 §8 grep 护栏 | `1 kept, 0 broken` + 护栏 exit 0 |
| `make gen` | OpenAPI 契约 → Pydantic 模型代码生成 | 生成 `libs/contracts_gen/identity_org_models.py`（确定性、无时间戳）|
| `make dev-up` | 起本地 Keycloak + MinIO（docker-compose）| 见 §4 |
| `make dev-down` | 停并清空本地依赖（含数据卷）| — |
| `make test-integration` | 集成测试（需先 `make dev-up`）| ⚠️ 见 §5（任务 9 待实现）|

跑单个测试：

```bash
uv run pytest tests/authz/test_can.py -q          # 单文件
uv run pytest tests/authz/test_can.py::test_can_v1_matrix -q   # 单用例
```

> 直接敲裸 `pytest` / `lint-imports` 会找不到命令——它们装在 uv 管理的 `.venv` 里，必须用 `uv run <cmd>` 或 `make <target>`。

---

## 4. 起本地环境（Keycloak + MinIO）

```bash
make dev-up
# 首次拉镜像稍慢；Keycloak 导入 realm 约需 ~15s
```

起来后：

| 服务 | 地址 | 凭据 |
|---|---|---|
| **Keycloak** | http://localhost:8080 （Admin Console：`/admin`，`admin` / `admin`）| realm = `lite-ai` |
| **MinIO API** | http://localhost:9000 | `minio` / `minio123` |
| **MinIO Console** | http://localhost:9001 | `minio` / `minio123` |

**Seeded realm `lite-ai`**（见 `deploy/dev/keycloak/realm-lite-ai.json`，dev/test 共用同一份）：

- client `gateway`（secret `dev-secret`，开启 direct access grant；`groups` mapper 带全路径）
- 组织结构：`/platform-admins`、`/e-0001/g-0001/{admins,members}`
- 种子用户：**`alice` / `alice`**，归属 `/e-0001/g-0001/members`

**验证拿到带 `groups` claim 的 token**（S0 出口 ②）：

```bash
TOKEN=$(curl -s -d client_id=gateway -d client_secret=dev-secret \
  -d username=alice -d password=alice -d grant_type=password \
  http://localhost:8080/realms/lite-ai/protocol/openid-connect/token \
  | uv run python -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
uv run python -c "import jwt;print(jwt.decode('$TOKEN',options={'verify_signature':False})['groups'])"
# 期望：['/e-0001/g-0001/members']
```

停掉：`make dev-down`。

---

## 5. 网关服务 / 集成测试（任务 9，已落地）

S0 交付**库 + 网关 + 契约 + 真依赖集成层**。单元层用 `x-test-claims` seam 和内存审计 double（无需真依赖）；集成层打真 Keycloak/MinIO：

- `services/gateway/main.py` —— 运行时装配（env → boto3(path-style)→MinIO/OSS → ASGI app）
- `libs/identity/tokens.py` —— Keycloak JWKS 验签（JWKS client 按 url 缓存；`LITEAI_TOKEN_ISSUER`/`LITEAI_TOKEN_AUDIENCE` 给定时强制校验）
- `tests/integration/` + `tests/conftest.py` —— 真 MinIO 写读 + 真 Keycloak token 验签

跑集成：`make dev-up && make test-integration`（期望 `2 passed`）。

起真网关（真验签）：

```bash
LITEAI_JWKS_URL=http://localhost:8080/realms/lite-ai/protocol/openid-connect/certs \
  OSS_ENDPOINT=http://localhost:9000 OSS_ACCESS_KEY=minio OSS_SECRET_KEY=minio123 \
  AUDIT_BUCKET=lite-ai uv run uvicorn services.gateway.main:app --port 8000
```

> 安全：`x-test-claims` 测试 seam **默认关闭**（default-deny）；仅显式 `LITEAI_ALLOW_TEST_CLAIMS=1`（单测/本地调试）才生效，生产装配绝不设置。

---

## 6. 代码结构

```
lite-ai-infra/
├── contracts/openapi/identity-org.yaml   # API 契约（API-first 真相源）
├── libs/
│   ├── identity/context.py     # Keycloak groups claim → 带 scope 的 Context（role_in 解析）
│   ├── authz/{types,engine}.py # Resource/Decision + can()：唯一授权出入口（宪法 §2.4）
│   ├── audit/oss_audit.py      # AuditSink 接口 + 尽力写 AuditWriter（ADR-010/013）
│   └── contracts_gen/          # 由契约生成的 Pydantic 模型（make gen 产物，已提交）
├── services/gateway/{app,deps}.py        # FastAPI 网关骨架：token→can()→audit
├── deploy/dev/                 # 本地 docker-compose（Keycloak 26.6.2 + MinIO）+ seeded realm
├── scripts/ci_guards.sh        # 宪法 §8 grep 护栏
├── tests/                      # 单元（零依赖）+ integration/（真 MinIO/Keycloak）
├── .python-version uv.lock pyproject.toml Makefile .importlinter
└── .github/workflows/ci.yml    # CI：单元 + lint + 护栏 + oasdiff + codegen freshness
```

分层纪律（宪法 §4.1，import-linter 强制）：`services → libs` 单向，`libs` 不得反向 import `services`。

---

## 7. 排错

**`make dev-up` 报 `port ... 8080: address already in use`**
说明 8080（或 9000/9001）被别的进程占了。查并处理：

```bash
lsof -nP -iTCP:8080 -sTCP:LISTEN          # 看谁占着
```

- 若是你自己的另一套服务（本机常驻），先停掉它，或临时改 `deploy/dev/docker-compose.yml` 里 Keycloak 的端口映射（如 `"8081:8080"`，但注意 §4 取 token 的 URL 与计划/测试默认都用 8080，改端口需同步改）。

**`uv run pytest` 报找不到模块**
先 `make sync` 建好 `.venv`；确认在仓库根目录运行（`pyproject.toml` 设了 `pythonpath=["."]`，`libs.*`/`services.*` 从根 import）。

**Keycloak 取 token 返回 `invalid_grant: Account is not fully set up`**
种子用户缺 `firstName`/`lastName`/`emailVerified`（Keycloak 26 默认开声明式 user profile 校验）——`realm-lite-ai.json` 已修复；若自建用户也需补齐这三项。

---

## 8. 环境矩阵

| 环境 | 位置 | 身份 | 对象存储 |
|---|---|---|---|
| dev | 本地 Mac（docker-compose）| Keycloak 26.6.2 容器 | MinIO（S3 兼容）|
| test | 阿里云 ACK | ACK 上 Keycloak 26.6.2 | 阿里云 OSS |
| CI | GitHub Actions | 集成 job 用容器 Keycloak | 集成 job 用容器 MinIO |

CI 用 `astral-sh/setup-uv` + `uv sync` + `uv run` 复现同一 3.12 环境，跑单元 + lint + §8 护栏 + 契约 breaking（oasdiff）+ codegen 新鲜度校验。
