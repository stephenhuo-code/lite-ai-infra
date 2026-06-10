# S0 地基（身份 / 授权 / 契约）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. 步骤用 checkbox（`- [ ]`）跟踪。

**目标：** 立起 S0 代码地基 —— API 契约 + 代码生成 + 一个把 Keycloak token 解析成带 scope 的 `Context` 的 Org Service、单一出入口的薄 `can()`、以及 OSS 追加写审计；全部可在本地（Mac）docker-compose 上开发并测试。

**架构：** monorepo、面向微服务的包结构（宪法 §4）。API 优先：OpenAPI 契约放 `contracts/`，client 由契约生成。身份用 Keycloak 26.6.2（单 realm + Organizations + Group 子组编码角色），token 带 `groups` claim。授权是**唯一** `PolicyEngine.can(ctx, action, resource)` 出入口；S0 交付**薄 in-code 版**（认证 + 企业隔离 + owner + 角色门槛），接口设计成 v2 可零改 handler 换 Cerbos（ADR-011）。v1 无 PG；审计 append-only 到 OSS/MinIO（ADR-010/013）。

**技术栈：** **Python 3.12（基线）+ uv（环境/依赖管理）**、FastAPI、pytest、Keycloak 26.6.2、MinIO（本地，S3 兼容）、阿里云 OSS（测试/线上）、`oasdiff`（契约 breaking 校验）、keycloak-config-cli、docker-compose、GitHub Actions。

---

## 环境（重要）

| 环境 | 位置 | 用途 | 身份 | 对象存储 |
|---|---|---|---|---|
| **开发（dev）** | **本地 Mac**（Docker Desktop / Apple Silicon arm64）| 日常开发 + 单元 + 本地集成测试（TDD）| docker-compose 的 Keycloak 26.6.2 | **MinIO**（S3 API，docker-compose）|
| **测试（test）** | **阿里云**（ACK + OSS + Keycloak on ACK）| e2e / 真机 spike / 集成验收 | ACK 上的 Keycloak 26.6.2 | **阿里云 OSS** |
| CI | GitHub Actions | 单元（零依赖）+ 集成（service 容器起 MinIO/Keycloak）+ lint + 契约 breaking | 集成 job 用容器 Keycloak | 集成 job 用容器 MinIO |

**Python 基线（环境即工程，宪法 §5.8）：**
- **基线 Python 3.12**，用 **uv** 管理（机器上无 3.12 时 uv 自动获取）：`.python-version` 钉解释器、`uv.lock` 锁依赖 → **dev/CI/阿里云可复现同一环境**。
- 三处一致：`.python-version` = `3.12`、`pyproject.toml` `requires-python = ">=3.12"`、CI `uv python install 3.12`。
- **本计划所有命令都在 uv 管理的 3.12 环境内执行**：用 `uv run <cmd>`（如 `uv run pytest`）或 `make <target>`（Makefile 已封装 `uv run`）。下文出现的裸 `pytest`/`lint-imports`/`datamodel-codegen` 等价于 `uv run …`。

**本地 Mac 注意：**
- Keycloak 26.6.2、MinIO 镜像均为**多架构（arm64 原生）**，Docker Desktop 直接跑；个别无 arm64 的镜像才加 `platform: linux/amd64`（性能降级）。
- 端口：Keycloak `8080`、MinIO `9000/9001`。

**对象存储抽象（关键，去 moto）：** 审计经 **`AuditSink` 接口**（依赖反转），不直接吃 raw S3 client：
- `OssAuditSink(bucket, s3_client)` —— 真实现，本地 `boto3`→**MinIO**，阿里云 `boto3`→**OSS（S3 兼容 endpoint）**/`oss2`，**端点由 env 选择**。
- 测试用极小的 test double（`MemoryAuditSink` / `RaisingSink`，几行，属测试代码），**不引入 moto**。

**测试两层（不再用 moto）：**
- **单元（零依赖、最快、最多）**：纯逻辑（`context` 解析、`can()`、`_audit_key`、审计"写失败不抛"用 `RaisingSink`、gateway 接线用 `MemoryAuditSink`）。`pytest -q` 默认只跑这层（`-m "not integration"`）。
- **本地集成（真 MinIO + 真 Keycloak）**：`@pytest.mark.integration`，打 docker-compose 的 MinIO（真写读）+ Keycloak（真 token 验签）。`make test-integration` 跑（需先 `make dev-up`）。
- **真机 e2e / spike**：跑**阿里云**（真 OSS + STS + ACK Keycloak）——见文末 Spike，标注"阿里云"。

> 为什么去 moto：身份验签本来就 moto 不了（需真 Keycloak），已有"真服务"集成层；把 S3 也并进去（MinIO，启动 ~2-3s）即可砍掉 moto，少一套机制、且 S3 行为真实。MinIO 启动很快，CI 成本可忽略（Keycloak 慢的那层本就需要）。

---

## 范围

**本计划内（Mac 上 TDD）：**
- monorepo 脚手架 + `contracts/` + OpenAPI 代码生成 + CI breaking 门禁
- 本地 dev `docker-compose`：Keycloak 26.6.2 + MinIO，含 seeded realm/Organization/groups
- `libs/identity`：Keycloak token claims → `Context`（enterprise_id / group_id / role）
- `libs/authz`：`Context`/`Resource` 类型 + `can()` 接口 + **薄实现**（v1 AC 子集）
- `libs/audit`：OSS/MinIO append-only 审计写入（client 可注入，本地 MinIO / 测试 OSS）
- `services/gateway`：FastAPI 骨架，串 token 中间件 → `can()` → 审计
- CI 护栏：import-linter 分层、grep `display_name`、grep 散落 `if enterprise_id ==`、`oasdiff` breaking

**本计划外（另立 ops 计划 / spike）：**
- 阿里云 ACK 集群、Volcano/Kueue/KubeRay/Argo Helm、Gravitino/MLflow/OpenSearch 部署 → **ops/IaC 清单**
- 数据 spike：Lance-on-OSS 延迟、Data-Juicer+Ray 多模态 → **spike 任务**
- Keycloak-Organizations 真机验证、Cerbos seam 真机验证 → **spike（跑阿里云/本地 compose）**
- Cerbos PDP（v2）、PG/Quota/Provisioner 业务逻辑（推迟，ADR-010/013）

> 真相源：`docs/constitution.md`、`docs/adr/ADR-010/011/013`、design §3.0/§3.2、`docs/user-stories/tenant-team-scenarios.md`（AC 表）。薄 `can()` 只强制 **v1 标注**的 AC 子集（AC-1/2/4/5/6/9/10/13/15/18 等）；用户组 scope/共享/派生类 AC 属 v2（Cerbos）。

---

## 文件结构

```
lite-ai-infra/
├── contracts/
│   └── openapi/identity-org.yaml      # Org Service API 契约（真相源）
├── libs/
│   ├── identity/{__init__.py, context.py, tokens.py}   # Context + 解析；JWKS 验签
│   ├── authz/{__init__.py, types.py, engine.py}        # Resource/Decision + can() 薄实现
│   └── audit/{__init__.py, oss_audit.py}               # 追加写审计（client 注入）
├── services/gateway/{app.py, deps.py}                  # FastAPI app + 中间件 + 示例路由
├── deploy/dev/
│   ├── docker-compose.yml             # 本地 Mac：Keycloak 26.6.2 + MinIO
│   └── keycloak/realm-lite-ai.json    # seeded realm + Organization + groups + mapper
├── tests/{identity,authz,audit,gateway}/...
├── Makefile  pyproject.toml  .importlinter  .github/workflows/ci.yml
```

---

### 任务 1：仓库脚手架 + uv/3.12 可复现环境

**文件：**
- 创建：`.python-version`、`pyproject.toml`、`Makefile`、`.importlinter`、`.gitignore`

- [x] **步骤 1：钉 Python 基线 + `.gitignore`**

`.python-version`（单行）：
```
3.12
```
`.gitignore`（追加）：
```
.venv/
.superpowers/
__pycache__/
*.pyc
```

- [x] **步骤 2：创建 `pyproject.toml`**

```toml
[project]
name = "lite-ai-infra"
version = "0.0.0"
requires-python = ">=3.12"
dependencies = [
  "fastapi>=0.115", "uvicorn>=0.32", "pyjwt[crypto]>=2.9",
  "boto3>=1.35", "httpx>=0.27",
]
[project.optional-dependencies]
dev = ["pytest>=8", "pytest-asyncio>=0.24", "import-linter>=2.1"]

[tool.pytest.ini_options]
pythonpath = ["."]
asyncio_mode = "auto"
markers = ["integration: 需要本地 MinIO/Keycloak（docker-compose）的集成测试；默认不跑"]
addopts = "-m 'not integration'"   # 默认只跑单元（零依赖）；集成用 make test-integration
```

- [x] **步骤 3：创建 `Makefile`**（命令统一经 `uv run`，环境即 uv 管理的 3.12 venv）

```make
.PHONY: test test-integration lint contract-check dev-up dev-down sync
sync:             ; uv sync --extra dev               # 建/同步 .venv(3.12)（按 uv.lock）
test:             ; uv run pytest -q                  # 单元（零依赖，默认 -m "not integration"）
test-integration: ; uv run pytest -q -m integration   # 需先 make dev-up（本地 MinIO+Keycloak）
lint:             ; uv run lint-imports && bash scripts/ci_guards.sh
contract-check:   ; oasdiff breaking contracts/openapi/identity-org.yaml@HEAD~1 contracts/openapi/identity-org.yaml || true
dev-up:           ; docker compose -f deploy/dev/docker-compose.yml up -d
dev-down:         ; docker compose -f deploy/dev/docker-compose.yml down -v
```

- [x] **步骤 4：创建 `.importlinter`（强制分层：services → libs，libs 不依赖 services）**

```ini
[importlinter]
root_packages = libs, services

[importlinter:contract:layers]
name = layering
type = layers
layers =
    services
    libs
```

- [x] **步骤 5：用 uv 建可复现环境 + 验证**

运行：
```bash
uv lock                 # 生成 uv.lock（uv 按 .python-version 自动获取 Python 3.12）
make sync               # uv sync --extra dev → 建 .venv(3.12) 并按 lock 安装
make test               # = uv run pytest -q
```
预期：`uv run pytest` 报 `no tests ran`（收集 0 个）—— 3.12 环境就绪、可复现、无报错。

- [x] **步骤 6：提交**

```bash
git add .python-version pyproject.toml uv.lock Makefile .importlinter .gitignore
git commit -m "chore: bootstrap monorepo + uv-managed Python 3.12 env (pinned + locked)"
```

---

### 任务 2：本地 dev docker-compose（Mac：Keycloak 26.6.2 + MinIO）+ seeded realm

**文件：**
- 创建：`deploy/dev/docker-compose.yml`、`deploy/dev/keycloak/realm-lite-ai.json`

- [x] **步骤 1：创建 `deploy/dev/docker-compose.yml`**（arm64 原生，Mac Docker Desktop 直接跑）

```yaml
services:
  keycloak:
    image: quay.io/keycloak/keycloak:26.6.2
    command: ["start-dev", "--import-realm", "--features=organization"]
    environment:
      KC_BOOTSTRAP_ADMIN_USERNAME: admin
      KC_BOOTSTRAP_ADMIN_PASSWORD: admin
    ports: ["8080:8080"]
    volumes:
      - ./keycloak:/opt/keycloak/data/import:ro
  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: minio
      MINIO_ROOT_PASSWORD: minio123
    ports: ["9000:9000", "9001:9001"]
```

- [x] **步骤 2：创建 `deploy/dev/keycloak/realm-lite-ai.json`**（realm + client + 子组 + `groups` mapper + 种子用户）

```json
{
  "realm": "lite-ai", "enabled": true,
  "clients": [{
    "clientId": "gateway", "publicClient": false, "secret": "dev-secret",
    "directAccessGrantsEnabled": true, "standardFlowEnabled": true, "redirectUris": ["*"],
    "protocolMappers": [{
      "name": "groups", "protocol": "openid-connect",
      "protocolMapper": "oidc-group-membership-mapper",
      "config": {"full.path": "true", "claim.name": "groups",
                 "access.token.claim": "true", "id.token.claim": "true"}
    }]
  }],
  "groups": [
    {"name": "platform-admins"},
    {"name": "e-0001", "subGroups": [
      {"name": "g-0001", "subGroups": [{"name": "admins"}, {"name": "members"}]}
    ]}
  ],
  "users": [{
    "username": "alice", "enabled": true, "email": "alice@e-0001.test",
    "credentials": [{"type": "password", "value": "alice", "temporary": false}],
    "groups": ["/e-0001/g-0001/members"]
  }]
}
```

- [x] **步骤 3：起服务并验证 Keycloak 带 organization 特性导入成功（验证 26.6.2 修复）**

运行：`make dev-up && sleep 25 && curl -fsS http://localhost:8080/realms/lite-ai/.well-known/openid-configuration | head -c 120`
预期：JSON 含 `"issuer":"http://localhost:8080/realms/lite-ai"`（import 不崩 → 确认 26.6.2 的 organization+import 可用）。

- [x] **步骤 4：验证 token 带 full-path `groups` claim**

运行：
```bash
TOKEN=$(curl -fsS -d 'client_id=gateway' -d 'client_secret=dev-secret' \
  -d 'username=alice' -d 'password=alice' -d 'grant_type=password' \
  http://localhost:8080/realms/lite-ai/protocol/openid-connect/token | uv run python -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
uv run python -c "import jwt;print(jwt.decode('$TOKEN',options={'verify_signature':False})['groups'])"
```
预期：`['/e-0001/g-0001/members']`

> 阿里云测试环境：同一份 `realm-lite-ai.json` 由 keycloak-config-cli apply 到 ACK 上的 Keycloak（ops 计划负责部署），保证 dev/test 配置一致。

- [x] **步骤 5：提交**

```bash
git add deploy/dev/docker-compose.yml deploy/dev/keycloak/realm-lite-ai.json
git commit -m "feat(dev): mac docker-compose Keycloak 26.6.2 + MinIO with seeded realm/org/groups"
```

---

### 任务 3：`Context` 模型 + token claims 解析（TDD）

**文件：**
- 创建：`libs/identity/context.py`、`tests/identity/test_context.py`

- [x] **步骤 1：写失败测试**

```python
# tests/identity/test_context.py
import pytest
from libs.identity.context import parse_context, Context, Membership

def test_parse_member_single_group():
    ctx = parse_context(sub="u-alice", groups=["/e-0001/g-0001/members"])
    assert ctx == Context(user="u-alice",
                          memberships=[Membership("e-0001", "g-0001", "member")])

def test_parse_group_admin():
    ctx = parse_context(sub="u-lead", groups=["/e-0001/g-0001/admins"])
    assert ctx.memberships[0].role == "group-admin"

def test_parse_enterprise_admin_no_group():
    ctx = parse_context(sub="u-ea", groups=["/e-0001/admins"])
    assert ctx.memberships[0] == Membership("e-0001", None, "enterprise-admin")

def test_parse_platform_admin():
    ctx = parse_context(sub="u-p", groups=["/platform-admins"])
    assert ctx.is_platform_admin is True

def test_role_in_resolves_active_membership():
    ctx = parse_context(sub="u-x",
                        groups=["/e-0001/g-0001/admins", "/e-0001/g-0002/members"])
    assert ctx.role_in("e-0001", "g-0001") == "group-admin"
    assert ctx.role_in("e-0001", "g-0002") == "member"
    assert ctx.role_in("e-0099", "g-0001") is None

def test_ignores_unparseable_groups():
    ctx = parse_context(sub="u", groups=["/garbage", "/e-0001/g-0001/members"])
    assert len(ctx.memberships) == 1
```

- [x] **步骤 2：运行验证失败**

运行：`pytest tests/identity/test_context.py -q`
预期：FAIL —— `ModuleNotFoundError: libs.identity.context`

- [x] **步骤 3：写最小实现**

```python
# libs/identity/context.py
from __future__ import annotations
import re
from dataclasses import dataclass, field

_RE_GROUP = re.compile(r"^/(?P<eid>e-[0-9a-z]+)/(?P<gid>g-[0-9a-z]+)/(?P<sub>admins|members)$")
_RE_ENT_ADMIN = re.compile(r"^/(?P<eid>e-[0-9a-z]+)/admins$")
_PLATFORM = "/platform-admins"
_ROLE = {"admins": "group-admin", "members": "member"}

@dataclass(frozen=True)
class Membership:
    enterprise_id: str
    group_id: str | None
    role: str  # member | group-admin | enterprise-admin

@dataclass(frozen=True)
class Context:
    user: str
    memberships: list[Membership] = field(default_factory=list)
    is_platform_admin: bool = False

    def role_in(self, enterprise_id: str, group_id: str | None = None) -> str | None:
        best = None
        for m in self.memberships:
            if m.enterprise_id != enterprise_id:
                continue
            if m.role == "enterprise-admin":
                best = "enterprise-admin"
            elif m.group_id == group_id and best != "enterprise-admin":
                best = m.role
        return best

def parse_context(sub: str, groups: list[str]) -> Context:
    memberships: list[Membership] = []
    is_platform = False
    for g in groups or []:
        if g == _PLATFORM:
            is_platform = True
            continue
        if (m := _RE_GROUP.match(g)):
            memberships.append(Membership(m["eid"], m["gid"], _ROLE[m["sub"]]))
        elif (m := _RE_ENT_ADMIN.match(g)):
            memberships.append(Membership(m["eid"], None, "enterprise-admin"))
    return Context(user=sub, memberships=memberships, is_platform_admin=is_platform)
```

- [x] **步骤 4：运行验证通过**

运行：`pytest tests/identity/test_context.py -q`
预期：PASS（6 passed）

- [x] **步骤 5：提交**

```bash
git add libs/identity/context.py tests/identity/test_context.py
git commit -m "feat(identity): parse Keycloak groups claim into scoped Context"
```

---

### 任务 4：授权类型 + `can()` 薄引擎（TDD，按 v1 AC 子集）

**文件：**
- 创建：`libs/authz/types.py`、`libs/authz/engine.py`、`tests/authz/test_can.py`

- [x] **步骤 1：写 `libs/authz/types.py`**（纯数据，无需测试）

```python
# libs/authz/types.py
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class Resource:
    kind: str                  # "job" | "dataset" | "pipeline" | ...
    enterprise_id: str
    group_id: str | None = None
    scope: str = "private"     # "private" | "shared"
    owner: str | None = None
    attrs: dict | None = None  # 例：{"gpu": 8, "state": "running"}

@dataclass(frozen=True)
class Decision:
    allow: bool
    reason: str = ""
```

- [x] **步骤 2：写失败测试**（每行 = 一条 AC；v1 子集，参数化）

```python
# tests/authz/test_can.py
import pytest
from libs.identity.context import parse_context
from libs.authz.types import Resource
from libs.authz.engine import can

def ctx(groups, sub="u-alice"):
    return parse_context(sub=sub, groups=groups)

ALICE = ["/e-0001/g-0001/members"]
LEAD  = ["/e-0001/g-0001/admins"]
PADM  = ["/platform-admins"]
JOB = lambda **k: Resource(kind="job", enterprise_id="e-0001", group_id="g-0001", **k)

@pytest.mark.parametrize("name,context,action,resource,expect_allow,reason_sub", [
  ("AC-1",  ctx(ALICE), "job.delete", JOB(owner="u-alice", attrs={"state":"running"}), True, ""),
  ("AC-2",  ctx(ALICE), "job.delete", JOB(owner="u-bob", attrs={"state":"running"}), False, "owner"),
  ("AC-4",  ctx(ALICE), "job.submit", JOB(attrs={"gpu":4}), True, ""),
  ("AC-5",  ctx(ALICE), "job.submit", JOB(attrs={"gpu":8}), False, "group-admin"),
  ("AC-6",  ctx(ALICE), "dataset.read", Resource(kind="dataset", enterprise_id="e-0099"), False, "cross-enterprise"),
  ("AC-9",  ctx(LEAD),  "job.delete", JOB(owner="u-bob", attrs={"state":"running"}), True, ""),
  ("AC-10", ctx(LEAD),  "job.submit", JOB(attrs={"gpu":8}), True, ""),
  ("AC-15", ctx(PADM),  "job.delete", Resource(kind="job", enterprise_id="e-0099", owner="x"), False, "admin"),
])
def test_can_v1_matrix(name, context, action, resource, expect_allow, reason_sub):
    d = can(context, action, resource)
    assert d.allow is expect_allow, f"{name}: {d.reason}"
    assert reason_sub in d.reason
```

- [x] **步骤 3：运行验证失败**

运行：`pytest tests/authz/test_can.py -q`
预期：FAIL —— `ModuleNotFoundError: libs.authz.engine`

- [x] **步骤 4：写 `libs/authz/engine.py`**（唯一出入口；薄实现）

```python
# libs/authz/engine.py
from __future__ import annotations
from libs.identity.context import Context
from libs.authz.types import Resource, Decision

_ROLE_RANK = {"member": 0, "group-admin": 1, "enterprise-admin": 2}

def can(ctx: Context, action: str, resource: Resource) -> Decision:
    """v1 薄 PolicyEngine。授权的唯一出入口（宪法 §2.4）。
    强制：认证(=有 ctx) + 企业隔离 + owner + 角色门槛。
    用户组 scope / 共享 / 派生规则属 v2（Cerbos）——can() 签名不变。"""
    # platform-admin 只能走 /admin/* 特权路径；普通业务路径仍按企业隔离
    if ctx.is_platform_admin:
        return Decision(False, "platform-admin must use /admin/* privileged API")

    role = ctx.role_in(resource.enterprise_id, resource.group_id)
    if role is None:  # AC-6/13/26：硬企业隔离
        in_enterprise = any(m.enterprise_id == resource.enterprise_id for m in ctx.memberships)
        return Decision(False, "cross-group" if in_enterprise else "cross-enterprise")

    rank = _ROLE_RANK[role]
    # 角色门槛：大 GPU 作业需 group-admin+
    if action == "job.submit" and (resource.attrs or {}).get("gpu", 0) > 4 and rank < 1:
        return Decision(False, "> 4 GPU job requires group-admin+")
    # mutation 的 owner 检查
    if action.endswith((".delete", ".cancel", ".update")) and resource.owner not in (None, ctx.user):
        if rank < 1:
            return Decision(False, "only owner / group-admin / enterprise-admin")
    return Decision(True, "")
```

- [x] **步骤 5：运行验证通过**

运行：`pytest tests/authz/test_can.py -q`
预期：PASS（8 passed）

- [x] **步骤 6：提交**

```bash
git add libs/authz/types.py libs/authz/engine.py tests/authz/test_can.py
git commit -m "feat(authz): single can() chokepoint, thin v1 impl (enterprise/owner/role)"
```

---

### 任务 5：审计写入（`AuditSink` 依赖反转）+ 单元测试（零依赖）

**文件：**
- 创建：`libs/audit/oss_audit.py`、`tests/audit/test_oss_audit.py`

> 设计：审计经 **`AuditSink` 接口**（依赖反转）。真实现 `OssAuditSink` 吃注入的 boto3 client（本地 MinIO / 阿里云 OSS）。**单元测试用极小 test double（`MemoryAuditSink`/`RaisingSink`），零依赖、不引入 moto**；真 MinIO 写读在任务 9（集成）覆盖。

- [x] **步骤 1：写失败测试**（单元，用 test double）

```python
# tests/audit/test_oss_audit.py
import json
from libs.audit.oss_audit import AuditWriter, AuditEvent, _audit_key

EV = AuditEvent(ts="2026-06-08T00:00:00Z", enterprise_id="e-0001", group_id="g-0001",
                actor_user="u-alice", actor_role="member", action="job.cancel",
                resource_uri="job/abc", decision="allow", override=False, reason="", metadata={})

class MemoryAuditSink:
    def __init__(self): self.items = []
    def put(self, key, body): self.items.append((key, body))

class RaisingSink:
    def put(self, key, body): raise RuntimeError("oss down")

def test_audit_key_partitioned_by_date():
    k = _audit_key(EV)
    assert k.startswith("audit/2026/06/08/") and k.endswith(".jsonl")

def test_write_returns_key_and_records():
    sink = MemoryAuditSink()
    key = AuditWriter(sink).write(EV)
    assert key and len(sink.items) == 1
    assert json.loads(sink.items[0][1])["action"] == "job.cancel"

def test_write_never_raises_into_caller():
    # 尽力写：sink 抛错也不得抛给调用方（ADR-010 v1 非原子）
    assert AuditWriter(RaisingSink()).write(EV) is None
```

- [x] **步骤 2：运行验证失败**

运行：`pytest tests/audit/test_oss_audit.py -q`
预期：FAIL —— `ModuleNotFoundError: libs.audit.oss_audit`

- [x] **步骤 3：写 `libs/audit/oss_audit.py`**

```python
# libs/audit/oss_audit.py
from __future__ import annotations
import json, logging, uuid
from dataclasses import dataclass, asdict
from typing import Protocol

log = logging.getLogger("audit")

@dataclass(frozen=True)
class AuditEvent:
    ts: str
    enterprise_id: str
    group_id: str | None
    actor_user: str
    actor_role: str
    action: str
    resource_uri: str
    decision: str          # allow | deny
    override: bool
    reason: str
    metadata: dict

def _audit_key(ev: AuditEvent) -> str:
    y, m, d = ev.ts[0:4], ev.ts[5:7], ev.ts[8:10]
    return f"audit/{y}/{m}/{d}/{ev.ts}-{uuid.uuid4().hex[:8]}.jsonl"

class AuditSink(Protocol):
    def put(self, key: str, body: bytes) -> None: ...

class OssAuditSink:
    """真实现：boto3 S3 client —— 本地 MinIO / 阿里云 OSS（S3 兼容 endpoint）。"""
    def __init__(self, bucket: str, client):
        self._bucket = bucket
        self._s3 = client
    def put(self, key: str, body: bytes) -> None:
        self._s3.put_object(Bucket=self._bucket, Key=key, Body=body)

class AuditWriter:
    """追加写审计；尽力写（ADR-010/013）：sink 失败仅记日志、绝不抛给调用方。"""
    def __init__(self, sink: AuditSink):
        self._sink = sink
    def write(self, ev: AuditEvent) -> str | None:
        key = _audit_key(ev)
        try:
            self._sink.put(key, json.dumps(asdict(ev)).encode())
            return key
        except Exception:
            log.exception("audit write failed (best-effort, dropped): %s", ev.action)
            return None
```

- [x] **步骤 4：运行验证通过**

运行：`pytest tests/audit/test_oss_audit.py -q`
预期：PASS（3 passed）

- [x] **步骤 5：提交**

```bash
git add libs/audit/oss_audit.py tests/audit/test_oss_audit.py
git commit -m "feat(audit): AuditSink + best-effort AuditWriter (ADR-010/013), unit-tested"
```

---

### 任务 6：Gateway 骨架 —— token 中间件 → can() → audit（TDD）

**文件：**
- 创建：`services/gateway/deps.py`、`services/gateway/app.py`、`tests/gateway/test_gateway.py`

- [x] **步骤 1：写失败测试**（FastAPI TestClient；token 验签用测试 seam 旁路）

```python
# tests/gateway/test_gateway.py
import json
from fastapi.testclient import TestClient
from libs.audit.oss_audit import AuditWriter

class MemoryAuditSink:                       # 测试 double（零依赖，不用 moto/MinIO）
    def __init__(self): self.items = []
    def put(self, key, body): self.items.append((key, body))

def _client(sink):
    from services.gateway.app import build_app
    return TestClient(build_app(audit=AuditWriter(sink)))

def _hdr(sub, groups):
    return {"x-test-claims": json.dumps({"sub": sub, "groups": groups})}

def test_unauthenticated_returns_401():
    client = _client(MemoryAuditSink())
    assert client.get("/v1/jobs/abc").status_code == 401     # AC-18

def test_allowed_request_passes_and_audits():
    sink = MemoryAuditSink(); client = _client(sink)
    r = client.request("DELETE", "/v1/jobs/job-1", headers=_hdr("u-alice", ["/e-0001/g-0001/members"]))
    assert r.status_code == 200                              # AC-1
    assert len(sink.items) == 1 and sink.items[0][0].startswith("audit/")

def test_cross_enterprise_denied_403_and_audited():
    sink = MemoryAuditSink(); client = _client(sink)
    r = client.request("DELETE", "/v1/jobs/e-0099:job-9", headers=_hdr("u-alice", ["/e-0001/g-0001/members"]))
    assert r.status_code == 403                              # AC-6/15
    assert "cross-enterprise" in r.json()["reason"]
    assert len(sink.items) == 1                              # deny 也审计
```

> `x-test-claims` 是**仅测试**注入（seam 在 `deps.py`）；真 JWKS 验签需活的 Keycloak —— 走任务 9 集成 / Spike A。生产路径解码并验签 bearer token。审计用 `MemoryAuditSink`（零依赖）；真 MinIO 写读在任务 9 覆盖。

- [x] **步骤 2：运行验证失败**

运行：`pytest tests/gateway/test_gateway.py -q`
预期：FAIL —— `ModuleNotFoundError: services.gateway.app`

- [x] **步骤 3：写 `services/gateway/deps.py`**（request → Context）

```python
# services/gateway/deps.py
import json, os
from fastapi import Request, HTTPException
from libs.identity.context import parse_context, Context

def context_from_request(request: Request) -> Context:
    # 测试 seam：设置 LITEAI_ALLOW_TEST_CLAIMS 时接受预解码 claims。
    raw = request.headers.get("x-test-claims")
    if raw and os.getenv("LITEAI_ALLOW_TEST_CLAIMS", "1") == "1":
        c = json.loads(raw)
        return parse_context(sub=c["sub"], groups=c.get("groups", []))
    # 生产：验 bearer JWT（Keycloak JWKS，Spike A / 阿里云）。无 token → 401。
    raise HTTPException(status_code=401, detail="unauthenticated")
```

- [x] **步骤 4：写 `services/gateway/app.py`**

```python
# services/gateway/app.py
from datetime import datetime, timezone
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from libs.authz.engine import can
from libs.authz.types import Resource
from libs.audit.oss_audit import AuditWriter, AuditEvent
from services.gateway.deps import context_from_request

def _parse_job_ref(ref: str) -> Resource:
    # "e-0099:job-9" -> 跨企业；"job-1" -> 默认本企业 e-0001/g-0001
    if ":" in ref:
        eid, _ = ref.split(":", 1)
        return Resource(kind="job", enterprise_id=eid, group_id=None, owner="someone")
    return Resource(kind="job", enterprise_id="e-0001", group_id="g-0001", owner="u-alice",
                    attrs={"state": "running"})

def build_app(audit: AuditWriter) -> FastAPI:
    """audit 由调用方注入（AuditWriter）：dev/集成传 OssAuditSink+MinIO/OSS；单测传 MemoryAuditSink。"""
    app = FastAPI()

    @app.delete("/v1/jobs/{ref}")
    def delete_job(ref: str, request: Request):
        ctx = context_from_request(request)            # 未认证 → 401
        resource = _parse_job_ref(ref)
        d = can(ctx, "job.delete", resource)            # 唯一出入口
        role = ctx.role_in(resource.enterprise_id, resource.group_id) or "none"
        audit.write(AuditEvent(
            ts=datetime.now(timezone.utc).isoformat(), enterprise_id=resource.enterprise_id,
            group_id=resource.group_id, actor_user=ctx.user, actor_role=role,
            action="job.delete", resource_uri=f"job/{ref}",
            decision="allow" if d.allow else "deny", override=False, reason=d.reason,
            metadata={"ip": request.client.host if request.client else ""}))
        if not d.allow:
            return JSONResponse(status_code=403, content={"reason": d.reason})
        return {"status": "deleted", "ref": ref}
    return app
```

- [x] **步骤 5：运行验证通过**

运行：`pytest tests/gateway/test_gateway.py -q`
预期：PASS（3 passed）

- [x] **步骤 6：跑全量 + import-linter**

运行：`pytest -q && lint-imports`
预期：全绿；import-linter `Contracts: 1 kept, 0 broken`。

- [x] **步骤 7：提交**

```bash
git add services/gateway/ tests/gateway/test_gateway.py
git commit -m "feat(gateway): skeleton wiring auth -> can() chokepoint -> OSS audit"
```

---

### 任务 7：OpenAPI 契约 + 端点 + CI（API 优先门禁）

**文件：**
- 创建：`contracts/openapi/identity-org.yaml`、`.github/workflows/ci.yml`

- [x] **步骤 1：写 `contracts/openapi/identity-org.yaml`**（首个契约，真相源）

```yaml
openapi: 3.1.0
info: {title: identity-org, version: 0.1.0}
paths:
  /v1/me/orgs:
    get:
      summary: 从 token 解析调用者的 企业/组/角色 成员关系
      responses:
        '200':
          description: memberships
          content:
            application/json:
              schema: {$ref: '#/components/schemas/Memberships'}
        '401': {description: unauthenticated}
components:
  schemas:
    Membership:
      type: object
      required: [enterprise_id, role]
      properties:
        enterprise_id: {type: string, pattern: '^e-[0-9a-z]+$'}
        group_id: {type: [string, 'null'], pattern: '^g-[0-9a-z]+$'}
        role: {type: string, enum: [member, group-admin, enterprise-admin]}
    Memberships:
      type: object
      properties:
        user: {type: string}
        is_platform_admin: {type: boolean}
        memberships: {type: array, items: {$ref: '#/components/schemas/Membership'}}
```

- [x] **步骤 2：在 gateway 加 `GET /v1/me/orgs`，返回契约结构**

在 `services/gateway/app.py` 的 `build_app` 内追加：

```python
    @app.get("/v1/me/orgs")
    def me_orgs(request: Request):
        ctx = context_from_request(request)
        return {"user": ctx.user, "is_platform_admin": ctx.is_platform_admin,
                "memberships": [{"enterprise_id": m.enterprise_id, "group_id": m.group_id,
                                 "role": m.role} for m in ctx.memberships]}
```

- [x] **步骤 3：加测试断言端点匹配契约结构**

```python
# 追加到 tests/gateway/test_gateway.py
def test_me_orgs_matches_contract():
    client = _client(MemoryAuditSink())
    r = client.get("/v1/me/orgs", headers=_hdr("u-alice", ["/e-0001/g-0001/members"]))
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"user", "is_platform_admin", "memberships"}
    assert body["memberships"][0] == {"enterprise_id": "e-0001", "group_id": "g-0001", "role": "member"}
```

- [x] **步骤 4：运行验证通过**

运行：`pytest tests/gateway/test_gateway.py::test_me_orgs_matches_contract -q`
预期：PASS

- [x] **步骤 5：写 `.github/workflows/ci.yml`**（单元测试 + lint + 契约 breaking 门禁，跑在 GitHub Actions，不依赖真环境）

```yaml
name: ci
on: [push, pull_request]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: {fetch-depth: 2}
      - uses: astral-sh/setup-uv@v5         # uv 装好；按 .python-version 取 3.12
      - run: uv sync --extra dev            # 按 uv.lock 复现 3.12 环境
      - run: uv run pytest -q               # 单元（零依赖，默认 -m "not integration"）
      - run: uv run lint-imports
      - run: bash scripts/ci_guards.sh
      - name: contract breaking-change check
        uses: oasdiff/oasdiff-action/breaking@v0.0.21
        with: {base: 'contracts/openapi/identity-org.yaml@HEAD~1', revision: 'contracts/openapi/identity-org.yaml'}
        continue-on-error: true              # 首个稳定 tag 前仅告警
```

- [x] **步骤 6：提交**

```bash
git add contracts/openapi/identity-org.yaml services/gateway/app.py tests/gateway/test_gateway.py .github/workflows/ci.yml
git commit -m "feat(contracts): identity-org OpenAPI + /v1/me/orgs + CI (test/lint/oasdiff)"
```

---

### 任务 8：CI 护栏脚本（宪法 §8 grep 守卫）（TDD）

**文件：**
- 创建：`scripts/ci_guards.sh`、`tests/test_ci_guards.py`

- [x] **步骤 1：写失败测试**

```python
# tests/test_ci_guards.py
import subprocess

def test_guards_pass_on_clean_tree():
    r = subprocess.run(["bash", "scripts/ci_guards.sh"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
```

- [x] **步骤 2：运行验证失败**

运行：`pytest tests/test_ci_guards.py -q`
预期：FAIL —— `No such file or directory: scripts/ci_guards.sh`

- [x] **步骤 3：写 `scripts/ci_guards.sh`**（宪法 §8）

```bash
#!/usr/bin/env bash
set -euo pipefail
fail=0
# 守卫 1：display_name 不得出现在资源命名代码（libs/services 的 .py）
if grep -rnE 'display_name' libs services --include='*.py' | grep -viE 'test|comment'; then
  echo "GUARD FAIL: display_name referenced in code"; fail=1; fi
# 守卫 2：authz 引擎之外不得散落 'if ... enterprise_id ==' (必须经 can())
if grep -rnE 'if .*enterprise_id *==' libs services --include='*.py' | grep -v 'libs/authz/engine.py'; then
  echo "GUARD FAIL: scattered enterprise_id comparison (use can())"; fail=1; fi
exit $fail
```

- [x] **步骤 4：加可执行权限，运行验证通过**

运行：`chmod +x scripts/ci_guards.sh && pytest tests/test_ci_guards.py -q`
预期：PASS

- [x] **步骤 5：接入 CI** —— `.github/workflows/ci.yml` 已在任务 7 步骤 5 含 `bash scripts/ci_guards.sh`（确认存在即可）。

- [x] **步骤 6：提交**

```bash
git add scripts/ci_guards.sh tests/test_ci_guards.py
git commit -m "feat(ci): constitution §8 grep guards (display_name, scattered enterprise_id)"
```

---

### 任务 9：本地集成测试（真 MinIO + 真 Keycloak）+ 运行时装配

**文件：**
- 创建：`tests/conftest.py`、`tests/integration/test_audit_minio.py`、`tests/integration/test_token_verify.py`、`libs/identity/tokens.py`、`services/gateway/main.py`
- 修改：`services/gateway/deps.py`（加生产验签分支）

- [x] **步骤 1：写 `tests/conftest.py`**（集成 fixture；本地依赖未起则 skip）

```python
# tests/conftest.py
import socket, uuid, boto3, httpx, pytest

def _reachable(host, port):
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False

@pytest.fixture(scope="session")
def minio_s3():
    if not _reachable("localhost", 9000):
        pytest.skip("MinIO 未启动（先 `make dev-up`）")
    return boto3.client("s3", endpoint_url="http://localhost:9000",
                        aws_access_key_id="minio", aws_secret_access_key="minio123",
                        region_name="us-east-1")

@pytest.fixture
def minio_bucket(minio_s3):
    name = f"it-{uuid.uuid4().hex[:8]}"
    minio_s3.create_bucket(Bucket=name)
    yield name
    for o in minio_s3.list_objects_v2(Bucket=name).get("Contents", []):
        minio_s3.delete_object(Bucket=name, Key=o["Key"])
    minio_s3.delete_bucket(Bucket=name)

@pytest.fixture(scope="session")
def kc_token():
    if not _reachable("localhost", 8080):
        pytest.skip("Keycloak 未启动（先 `make dev-up`）")
    r = httpx.post("http://localhost:8080/realms/lite-ai/protocol/openid-connect/token",
                   data={"client_id": "gateway", "client_secret": "dev-secret",
                         "username": "alice", "password": "alice", "grant_type": "password"})
    r.raise_for_status()
    return r.json()["access_token"]
```

- [x] **步骤 2：写 `libs/identity/tokens.py`**（JWKS 验签）

```python
# libs/identity/tokens.py
from __future__ import annotations
import jwt
from jwt import PyJWKClient

def verify_and_decode(token: str, jwks_url: str, audience: str | None = None) -> dict:
    """用 Keycloak JWKS 验签并解码 access token。验签失败抛 jwt 异常。"""
    key = PyJWKClient(jwks_url).get_signing_key_from_jwt(token).key
    return jwt.decode(token, key, algorithms=["RS256"],
                      audience=audience, options={"verify_aud": audience is not None})
```

- [x] **步骤 3：扩展 `services/gateway/deps.py` 生产验签分支**

```python
# services/gateway/deps.py  （替换整个文件）
import json, os
from fastapi import Request, HTTPException
from libs.identity.context import parse_context, Context
from libs.identity.tokens import verify_and_decode

def context_from_request(request: Request) -> Context:
    # 测试 seam：LITEAI_ALLOW_TEST_CLAIMS=1 时接受预解码 claims（默认 1，便于单测）
    raw = request.headers.get("x-test-claims")
    if raw and os.getenv("LITEAI_ALLOW_TEST_CLAIMS", "1") == "1":
        c = json.loads(raw)
        return parse_context(sub=c["sub"], groups=c.get("groups", []))
    # 生产：Bearer JWT → Keycloak JWKS 验签 → 解析。无/非法 token → 401。
    authz = request.headers.get("authorization", "")
    if not authz.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="unauthenticated")
    try:
        claims = verify_and_decode(authz[7:], jwks_url=os.environ["LITEAI_JWKS_URL"])
    except Exception:
        raise HTTPException(status_code=401, detail="invalid token")
    return parse_context(sub=claims["sub"], groups=claims.get("groups", []))
```

- [x] **步骤 4：写运行时装配 `services/gateway/main.py`**（env → boto3→MinIO/OSS → OssAuditSink → build_app）

```python
# services/gateway/main.py    启动：uvicorn services.gateway.main:app
import os, boto3
from libs.audit.oss_audit import OssAuditSink, AuditWriter
from services.gateway.app import build_app

def _audit_writer() -> AuditWriter:
    s3 = boto3.client(
        "s3",
        endpoint_url=os.environ["OSS_ENDPOINT"],        # MinIO http://localhost:9000 / OSS https://oss-...
        aws_access_key_id=os.environ["OSS_ACCESS_KEY"],
        aws_secret_access_key=os.environ["OSS_SECRET_KEY"],
        region_name=os.getenv("OSS_REGION", "us-east-1"))
    return AuditWriter(OssAuditSink(bucket=os.environ["AUDIT_BUCKET"], client=s3))

app = build_app(audit=_audit_writer())
```

- [x] **步骤 5：写集成测试（标 `integration`）**

```python
# tests/integration/test_audit_minio.py
import json, pytest
from libs.audit.oss_audit import OssAuditSink, AuditWriter, AuditEvent
pytestmark = pytest.mark.integration

def test_audit_real_minio_write_read(minio_s3, minio_bucket):
    w = AuditWriter(OssAuditSink(bucket=minio_bucket, client=minio_s3))
    ev = AuditEvent(ts="2026-06-08T00:00:00Z", enterprise_id="e-0001", group_id="g-0001",
                    actor_user="u-alice", actor_role="member", action="job.cancel",
                    resource_uri="job/abc", decision="allow", override=False, reason="", metadata={})
    key = w.write(ev)
    body = minio_s3.get_object(Bucket=minio_bucket, Key=key)["Body"].read().decode()
    assert json.loads(body)["action"] == "job.cancel"
```

```python
# tests/integration/test_token_verify.py
import pytest
from libs.identity.tokens import verify_and_decode
from libs.identity.context import parse_context
pytestmark = pytest.mark.integration
JWKS = "http://localhost:8080/realms/lite-ai/protocol/openid-connect/certs"

def test_real_token_verifies_and_parses(kc_token):
    claims = verify_and_decode(kc_token, jwks_url=JWKS)
    ctx = parse_context(sub=claims["sub"], groups=claims.get("groups", []))
    assert any(m.enterprise_id == "e-0001" and m.role == "member" for m in ctx.memberships)
```

- [x] **步骤 6：起本地依赖并跑集成**

运行：`make dev-up && sleep 25 && make test-integration`
预期：`2 passed`（真 MinIO 写读 + 真 Keycloak token 验签解析）。

- [x] **步骤 7：CI 加集成 job**（`.github/workflows/ci.yml` 追加，单独 job 起 compose 跑集成）

```yaml
  integration:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync --extra dev
      - run: docker compose -f deploy/dev/docker-compose.yml up -d
      - run: sleep 25
      - run: make test-integration
```

- [x] **步骤 8：提交**

```bash
git add tests/conftest.py tests/integration/ libs/identity/tokens.py services/gateway/main.py services/gateway/deps.py .github/workflows/ci.yml
git commit -m "feat: local integration (real MinIO+Keycloak) + gateway runtime wiring"
```

---

### 任务 10：契约代码生成（API 优先，满足 S0 出口 ④）

**文件：**
- 修改：`pyproject.toml`（dev 加生成器）、`Makefile`（`gen` 目标）、`.gitignore`
- 创建：`libs/contracts_gen/__init__.py`、`tests/test_codegen.py`

- [x] **步骤 1：dev 依赖加生成器** —— `pyproject.toml` 的 `dev` 列表追加 `"datamodel-code-generator>=0.26"`。

- [x] **步骤 2：`Makefile` 加 `gen` 目标**

```make
gen: ; uv run datamodel-codegen --input contracts/openapi/identity-org.yaml \
        --input-file-type openapi --output libs/contracts_gen/identity_org_models.py
```

- [x] **步骤 3：写失败测试**（生成后产物可 import 且含契约模型）

```python
# tests/test_codegen.py
import importlib, subprocess

def test_codegen_produces_importable_models():
    subprocess.run(["make", "gen"], check=True)
    m = importlib.import_module("libs.contracts_gen.identity_org_models")
    assert hasattr(m, "Membership") and hasattr(m, "Memberships")
```

- [x] **步骤 4：建包占位 + 运行**

运行：`touch libs/contracts_gen/__init__.py && uv run pytest tests/test_codegen.py -q`
预期：PASS —— `make gen` 跑通、生成 `libs/contracts_gen/identity_org_models.py`、可 import 出 `Membership`/`Memberships`（**契约代码生成跑通**，S0 出口 ④）。

- [x] **步骤 5：CI 加"生成物最新"校验** —— `.github/workflows/ci.yml` 的 build job 追加：

```yaml
      - run: make gen && git diff --exit-code libs/contracts_gen/   # 生成物必须已提交且最新
```

- [x] **步骤 6：提交**

```bash
git add pyproject.toml Makefile libs/contracts_gen/ tests/test_codegen.py .github/workflows/ci.yml
git commit -m "feat(contracts): OpenAPI -> Pydantic models codegen + CI freshness gate"
```

---

## S0 出口对照（design §5.3 Sprint 0）

| 出口条件 | 对应 |
|---|---|
| ② Keycloak 26.6.2 登录拿带 `groups` claim token | 任务 2（步骤 3/4 验证）+ 任务 9（真验签）|
| ③ Gateway 解析 enterprise_id/group_id | 任务 3 + 6 + 7（/v1/me/orgs）+ 9（真 token→gateway）|
| ④ contracts 代码生成跑通 | **任务 10** + 任务 7（契约 + oasdiff）|
| ① 两个数据 Spike PASS（Lance / Data-Juicer）| **数据 Spike 1 + 2**（下方，阿里云，S0 必做）|

---

## S0 验收 runbook（实现完成后照此验收）

> 原则（宪法 §3.2）：**证据先于断言**——每条跑命令看输出，不靠口头声称。

**A. 前置**：plan 任务 1–10 checkbox 全 `- [x]`、代码已合；本地 `make sync`（= `uv sync --extra dev`，按 `uv.lock` 复现 3.12 环境）+ `make dev-up`；阿里云测试环境就绪（仅出口① 数据 spike 需要）。

**B. 自动化验收（本地 Mac）**

```bash
uv run pytest -q                                   # 1) 单元全绿 → N passed
uv run lint-imports && bash scripts/ci_guards.sh   # 2) 分层 + §8 护栏 → 0 broken / exit 0
make gen && uv run pytest tests/test_codegen.py -q && git diff --exit-code libs/contracts_gen/  # 3) 出口④ codegen → pass + 无 diff
make dev-up && sleep 25 && make test-integration   # 4) 真 MinIO+Keycloak 集成 → 2 passed
```

**C. 4 个出口逐条人工验收（命令 + 期望证据）**

```bash
# 出口② Keycloak 拿带 groups 的 token
TOKEN=$(curl -fsS -d client_id=gateway -d client_secret=dev-secret \
  -d username=alice -d password=alice -d grant_type=password \
  http://localhost:8080/realms/lite-ai/protocol/openid-connect/token | uv run python -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
uv run python -c "import jwt;print(jwt.decode('$TOKEN',options={'verify_signature':False})['groups'])"
# 期望：['/e-0001/g-0001/members']

# 出口③ Gateway 解析 enterprise_id/group_id（真 token，验签开启）
LITEAI_ALLOW_TEST_CLAIMS=0 LITEAI_JWKS_URL=http://localhost:8080/realms/lite-ai/protocol/openid-connect/certs \
  OSS_ENDPOINT=http://localhost:9000 OSS_ACCESS_KEY=minio OSS_SECRET_KEY=minio123 AUDIT_BUCKET=lite-ai \
  uvicorn services.gateway.main:app --port 8000 &
curl -fsS -H "Authorization: Bearer $TOKEN" http://localhost:8000/v1/me/orgs
# 期望：memberships 含 {"enterprise_id":"e-0001","group_id":"g-0001","role":"member"}
curl -s -o /dev/null -w "%{http_code}" -X DELETE -H "Authorization: Bearer $TOKEN" http://localhost:8000/v1/jobs/e-0099:job-9
# 期望：403（cross-enterprise，企业隔离硬纪律生效）

# 出口④：见 B-3
# 出口①（阿里云，非 pass/fail，验收=有数据+结论）：
#   数据 Spike 1 Lance on OSS：读写延迟数据 + 通过/降级(JindoFS缓存)结论
#   数据 Spike 2 Data-Juicer+Ray：100GB 多模态跑通 + OOM 边界 + 分片/spill 兜底结论
```

**D. CI 绿**：GitHub Actions `build`（单元 + lint + 护栏 + oasdiff + codegen freshness）与 `integration`（compose 起 MinIO/Keycloak 跑集成）两个 job 全绿。

**E. Spike 结论已回写**：Spike A → ADR-010（多组织 claim 稳定性 + token-stale 窗口）；Spike B → ADR-011（can() 换 Cerbos 零改 handler 结论）；数据 Spike 1/2 → 结论 + go/降级决策（design §5 / spike 文档）。

**F. 签收门禁（DoD，硬阈值，不主观 Partial）**

- [ ] B + C 全部命令实测通过（贴输出为证）
- [ ] 出口 ①②③④ 四条全 PASS（任一 fail → **不验收**，触发 §5 滑窗）
- [ ] Spike A/B + 数据 Spike 结论已回写 ADR/文档
- [x] code review 过（`superpowers:requesting-code-review`）
- [x] plan 任务 1–10 checkbox 全 `- [x]`、commit 齐
- [ ] 团队 go/no-go 签字

---

## Spike（记录结论，不写生产代码）

- [ ] **Spike A —— Keycloak Organizations token（ADR-010/011，go/no-go）｜本地 compose + 阿里云复验**：26.6.2 开 `--features=organization`，建一个用户属**两个**组，确认 `groups` claim 带出两条全路径；改用户子组成员，测多久后**新签发**的 token 反映变更（token-stale 窗口）。本地 compose 先验，**阿里云测试环境复验一次**。结论写回 ADR-010。
- [ ] **Spike B —— Cerbos can() seam（ADR-011）｜本地**：起 Cerbos 容器，写 1 条 `job` 的 resource policy + derived role，确认**同一** `can(ctx, action, resource)` 签名能调 Cerbos 并复现 AC-1/AC-6，且 **`services/gateway/app.py` 零改**。结论写回 ADR-011。
- [ ] **Spike C —— 真 OSS 审计 + STS（阿里云）**：把审计 sink 换成 **`OssAuditSink` + 指向阿里云 OSS 的 boto3**（S3 兼容 endpoint）/oss2 适配器，验证追加写 + 路径前缀隔离 + STS 受限凭据（数据路径）。本地 MinIO 已覆盖逻辑（任务 9）；此步验真 OSS 兼容性。
- [ ] **数据 Spike 1（S0 出口 ①·必做）—— Lance on OSS 读写延迟｜阿里云**：100GB 子集在**阿里云 OSS** 上读写 Lance，测延迟（顺序/随机/列裁剪），判断能否满足训练 DataLoader 吞吐；**有 fallback 结论**（如 JindoFS/本地缓存）。验收：有延迟数据 + 通过/降级结论。
- [ ] **数据 Spike 2（S0 出口 ①·必做）—— Data-Juicer + Ray 多模态｜阿里云**：100GB **图文多模态**子集跑通 Data-Juicer + Ray 清洗，记录 **OOM 边界 + 分片/spill 兜底**结论。验收：跑通 + 资源边界数据。

> 这两个数据 spike 依赖阿里云 ACK + OSS + 数据栈（Ray/Data-Juicer/Lance），属测试环境；ops 前置就绪后执行（见文末"本计划外的前置"）。它们是 **S0 出口硬条件**，不达标触发 §5 滑窗。

---

## 本计划外的前置（ops/IaC，另立 runbook）

阿里云 ACK 集群 + 节点池；Helm：Volcano/Kueue/KubeRay/Argo；ACK 上 Keycloak 26.6.2（HA 2 副本 + RDS 主备，ADR-002）；Gravitino + MLflow 部署。这些是环境搭建（非 TDD 代码），产出独立的 `deploy/` runbook。dev/test 用同一份 `realm-lite-ai.json` 保证配置一致。
