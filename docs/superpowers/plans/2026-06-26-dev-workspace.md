# Dev Workspace 地基(探针 + 受控数据链路)Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 打通 Dev Workspace 的受控数据链路地基——omnigent(预构建镜像 + header-auth)作 agent 后端,BFF 铸每会话令牌并注册「我们的 MCP server」,agent 经令牌化 MCP 工具访问数据时每次过 `can()`(企业硬隔离 + owner),并以隔离负例证伪。

**Architecture:** 自托管 omnigent(prebuilt ghcr 镜像,header-auth 在 BFF 后)+ BFF 每会话令牌(`token→(sub, 企业, 角色, 会话)`)+ 我们的 http-transport MCP server(URL 内嵌令牌 → 还原 `Context` → `can()`)。本计划只做**后端受控链路**(headless 可验);前端/管线/持久化见末尾「后续计划」。

**Tech Stack:** Python 3.12 + FastAPI/Starlette;官方 `mcp` SDK(FastMCP streamable-http);现有 `libs.authz.can` / `libs.identity` / `services.gateway.bff` / `services.metadata_service.gravitino`;omnigent `ghcr.io/omnigent-ai/omnigent-server`(self-host);pytest(httpx MockTransport)。

**地基/契约:** spec/design `docs/superpowers/plans/2026-06-26-dev-workspace/{spec,design}.md`;ADR-026;高保真原型 `docs/superpowers/prototypes/2026-06-26-dev-workspace-hifi.html`;控制链路图 `.../assets/control-chain.svg`。

**门禁(全绿定义,来自仓库 Makefile):** `make test`(pytest)、`make lint`(import-linter + ci_guards)。涉及 docker 的 Task 0/1 另有手动 runbook。**TDD 红→绿,每步勾选,频繁提交。**

---

## File Structure(本计划新增/改动)

- `deploy/dev/omnigent.yml` — **新增**:omnigent self-host compose(prebuilt 镜像 pin + header-auth env + 仅 BFF 可达)。
- `docs/superpowers/spikes/2026-06-26-omnigent-probe-RESULTS.md` — **新增**:Task 0 探针实测事实 + 决策规则。
- `services/gateway/bff/wstoken.py` — **新增**:每会话工作区令牌——铸/验/映射(`token→(sub,企业,角色,会话)`),不透明 + TTL + 撤销。单一职责。
- `services/dev_workspace_mcp/__init__.py` — **新增**:包标记。
- `services/dev_workspace_mcp/identity.py` — **新增**:令牌 → `Context` 还原(contextvar 承载当前会话身份)。
- `services/dev_workspace_mcp/app.py` — **新增**:http-transport MCP server(FastMCP)+ 令牌路由包裹(`/s/{token}/mcp`)。
- `services/dev_workspace_mcp/tools/catalog.py` — **新增**:第一个数据工具 `catalog_read_schema`(读 Gravitino fileset,内调 `can()`)。
- `services/gateway/bff/workspace.py` — **新增**:BFF 工作区会话端点(建 omnigent 会话 + 铸令牌 + 注册我们的 MCP server;header-auth 注入 + 剥离伪造头)。
- `services/gateway/bff/omnigent_client.py` — **新增**:omnigent admin REST 薄客户端(建会话 / 注册 mcp-server;transport 可注入测试)。
- `tests/dev_workspace/` — **新增**:各 task 的单元/集成测试。
- `pyproject.toml` — **改**:加 `mcp` 依赖 + import-linter 合同(新包分层)。

---

## Task 0:omnigent 探针(承重墙实跑 · 非 TDD · 带决策规则)

> **目的**:在写任何受控链路代码前,用预构建镜像实跑确认 design 的四条假设;不成则记录 + 调整集成形态(退化规则),回写 design。**这是 DoR #4 外部依赖事实的兑现。**

**Files:**
- Create: `deploy/dev/omnigent.yml`(探针用最小版,Task 1 固化)
- Create: `docs/superpowers/spikes/2026-06-26-omnigent-probe-RESULTS.md`
- Create(临时探针脚手架,验证后删或并入 Task 3): `/tmp/omnigent-probe/ping_mcp.py`

- [ ] **Step 1:拉起 omnigent(prebuilt 镜像 + header-auth)**

写 `deploy/dev/omnigent.yml`(参照 `/tmp/omnigent-spike/deploy/docker/docker-compose.yaml`,但**只用 image 不 build**):
```yaml
services:
  omnigent:
    image: ghcr.io/omnigent-ai/omnigent-server:${OMNIGENT_TAG:-latest}   # Step 7 改为 :vX.Y.Z 钉定
    environment:
      OMNIGENT_AUTH_ENABLED: "1"
      OMNIGENT_AUTH_PROVIDER: "header"
      OMNIGENT_AUTH_HEADER: "X-Forwarded-Email"
    ports: ["8900:8000"]   # 探针期直连;Task 1 改为仅内网(不 ports 暴露)
```
Run: `docker compose -f deploy/dev/omnigent.yml up -d && sleep 20 && curl -s localhost:8900/healthz || curl -s localhost:8900/`
Expected: 服务起来(200 / 可达)。**退化**:若镜像拉取失败 → 记 RESULTS,改 `Dockerfile.prebuilt` 本地 build;若无 `/healthz` → 记真实健康端点。

- [ ] **Step 2:确认 header-auth(身份来自可信头)**

Run:
```bash
# 缺头 → 拒
curl -s -o /dev/null -w "%{http_code}\n" localhost:8900/v1/sessions
# 带头 → 通,身份=该邮箱
curl -s -X POST localhost:8900/v1/sessions -H 'X-Forwarded-Email: alice@acme.test' -H 'content-type: application/json' -d '{}'
```
Expected: 缺头 401/403;带头 200 且会话 owner = `alice@acme.test`。记录会话创建响应的真实字段(id 等)到 RESULTS。**退化**:若 header 名/行为不符 → 记真实约定。

- [ ] **Step 3:起一个最小的令牌化 MCP server(验"URL 嵌令牌"绑定)**

写 `/tmp/omnigent-probe/ping_mcp.py`(官方 `mcp` SDK,http transport,路径含令牌):
```python
import contextvars, uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.routing import Mount

_tok = contextvars.ContextVar("tok", default=None)
mcp = FastMCP("liteai-probe")

@mcp.tool()
def ping() -> str:
    return f"pong; token={_tok.get()}"   # 证明工具能拿到本会话令牌

inner = mcp.streamable_http_app()        # ASGI app
async def app(scope, receive, send):
    if scope["type"] == "http":
        parts = scope["path"].split("/")        # /s/<token>/mcp...
        if len(parts) > 2 and parts[1] == "s":
            _tok.set(parts[2])
            scope = dict(scope); scope["path"] = "/" + "/".join(parts[3:])
    await inner(scope, receive, send)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8901)
```
Run: `cd /tmp/omnigent-probe && uv run --with mcp --with uvicorn python ping_mcp.py &`
Expected: 监听 8901。**退化**:若 `streamable_http_app()` API 名不同 → 记 SDK 真实 API 到 RESULTS(决定 Task 3 写法);若 omnigent 不支持 http transport 只支持 stdio → 记录,Task 3/5 改 stdio + 令牌走 args/env(design 退化分支)。

- [ ] **Step 4:omnigent 会话注册我们的 MCP server 并让 agent 调用**

Run(用 Step 2 拿到的 session_id;令牌随便取个 `probe-tok-123`):
```bash
SID=<session_id>
curl -s -X POST localhost:8900/v1/sessions/$SID/agent/mcp-servers \
  -H 'X-Forwarded-Email: alice@acme.test' -H 'content-type: application/json' \
  -d '{"name":"liteai","transport":"http","url":"http://host.docker.internal:8901/s/probe-tok-123/mcp"}'
# 触发 agent 调用 ping(经 omnigent 的对话/turn 端点,具体端点 Step 记录)
```
Expected: 注册 201;agent 调 `ping` 返回 `pong; token=probe-tok-123` → **证明:omnigent 按注册 URL 原样调用,令牌随 URL 抵达我们工具**。把"触发一次 agent turn"的真实端点/字段记 RESULTS(Task 5/9b 要用)。**退化**:若 omnigent 容器内访问宿主用别的主机名 → 记;若 URL 被改写/丢令牌 → 触发 design 的"header 带令牌"备选(核验有无 header 转发槽)。

- [ ] **Step 5:确认沙箱限工作目录**

Run:让 agent 执行越界写(如 `echo x > /etc/probe` 或读 `/root`),观察是否被沙箱拒。
Expected: 越界被阻止;工作目录内读写正常。记录沙箱实现(bwrap/seatbelt)与工作目录挂载路径到 RESULTS。

- [ ] **Step 6:写 RESULTS(事实 + 决策规则)**

写 `docs/superpowers/spikes/2026-06-26-omnigent-probe-RESULTS.md`:逐条记 Step 1–5 的**真实端点/字段/响应/主机名/沙箱路径**,每条带"若 X 则 Y"决策规则,并标注哪几条**确认 / 推翻**了 design 假设(推翻的回写 design + 通知 owner)。

- [ ] **Step 7:钉定版本 + 收尾**

把 `omnigent.yml` 的 `:latest` 换成实测可用的 `:vX.Y.Z`(或 `:sha-<short>`);停掉探针容器与临时脚本。
Run: `docker compose -f deploy/dev/omnigent.yml down`

- [ ] **Step 8:Commit**
```bash
git add deploy/dev/omnigent.yml docs/superpowers/spikes/2026-06-26-omnigent-probe-RESULTS.md
git commit -m "spike(plan9): omnigent 探针 RESULTS(header-auth + 令牌化 MCP + 沙箱实证)"
```

> **门槛**:Step 4(令牌随 URL 抵达工具)与 Step 2(header-auth)必须通过,否则**停止后续 Task,回 design 调整**(本计划 Task 2–6 假设这两条成立)。

---

## Task 1:固化 omnigent 部署(仅 BFF 可达 + 版本钉定)

**Files:**
- Modify: `deploy/dev/omnigent.yml`(去掉对外 ports,接入内网;pin tag)
- Test: 手动 runbook(docker,无单测)

- [ ] **Step 1:改 compose 为"不直达"**

把 `ports: ["8900:8000"]` 删除(或仅绑 `127.0.0.1`),加入与 BFF 同一 docker network(`deploy/dev` 现有网络名见 `docker-compose.yml`),并固定镜像 tag:
```yaml
services:
  omnigent:
    image: ghcr.io/omnigent-ai/omnigent-server:vX.Y.Z   # Task0 实测值
    environment:
      OMNIGENT_AUTH_ENABLED: "1"
      OMNIGENT_AUTH_PROVIDER: "header"
      OMNIGENT_AUTH_HEADER: "X-Forwarded-Email"
    expose: ["8000"]            # 仅容器网内可见,不发布到宿主
    networks: [default]
```

- [ ] **Step 2:验证仅内网可达**

Run: `docker compose -f deploy/dev/omnigent.yml up -d && sleep 15 && curl -s -o /dev/null -w "%{http_code}\n" localhost:8900/ ; echo "(应连不上/拒绝)"`
Expected: 宿主直连失败(connection refused);容器网内可达(从 BFF 容器或同网容器 curl `http://omnigent:8000/` 成功)。

- [ ] **Step 3:Commit**
```bash
git add deploy/dev/omnigent.yml
git commit -m "feat(plan9): omnigent 部署固化(仅 BFF 可达 + 版本钉定)"
```

---

## Task 2:每会话工作区令牌(铸/验/映射)

> 受控链路的"绑定"核心:把不透明令牌映射到 `(sub, 企业 alias, 角色, 会话)`,带 TTL + 撤销。纯我们的代码,可独立 TDD。

**Files:**
- Create: `services/gateway/bff/wstoken.py`
- Test: `tests/dev_workspace/test_wstoken.py`

- [ ] **Step 1:写失败测试**
```python
# tests/dev_workspace/test_wstoken.py
import pytest
from services.gateway.bff.wstoken import WorkspaceTokenStore, TokenClaims

def _store():
    return WorkspaceTokenStore(ttl_seconds=3600, now=lambda: 1000)

def test_mint_then_resolve_roundtrip():
    s = _store()
    tok = s.mint(TokenClaims(sub="u-alice", enterprise="ent-demo", role="member", session="sess-1"))
    assert tok and "ent-demo" not in tok           # 不透明:不泄露身份
    c = s.resolve(tok)
    assert c.sub == "u-alice" and c.enterprise == "ent-demo" and c.role == "member" and c.session == "sess-1"

def test_resolve_unknown_token_returns_none():
    assert _store().resolve("nope") is None

def test_resolve_expired_returns_none():
    s = WorkspaceTokenStore(ttl_seconds=100, now=lambda: 1000)
    tok = s.mint(TokenClaims("u", "ent-demo", "member", "sess-1"))
    s._now = lambda: 1101                            # 过 TTL
    assert s.resolve(tok) is None

def test_revoke_session_invalidates_token():
    s = _store()
    tok = s.mint(TokenClaims("u", "ent-demo", "member", "sess-9"))
    s.revoke_session("sess-9")
    assert s.resolve(tok) is None
```

- [ ] **Step 2:运行验证失败**

Run: `uv run pytest tests/dev_workspace/test_wstoken.py -q`
Expected: FAIL(`No module named ...wstoken`)。

- [ ] **Step 3:最小实现**
```python
# services/gateway/bff/wstoken.py
# 每会话工作区令牌:不透明随机串 → (sub, 企业 alias, 角色, 会话)。带 TTL + 按会话撤销。
# v1 进程内存映射(单 BFF 实例够;多实例 = 换共享存储,此处是唯一改点)。令牌是 agent→MCP 工具的
# 唯一身份凭证(design「数据集受控链路」),故必须不透明 + 短时 + 可撤销。
from __future__ import annotations
import secrets, time
from dataclasses import dataclass

@dataclass(frozen=True)
class TokenClaims:
    sub: str
    enterprise: str
    role: str
    session: str

@dataclass(frozen=True)
class ResolvedToken:
    sub: str
    enterprise: str
    role: str
    session: str

class WorkspaceTokenStore:
    def __init__(self, ttl_seconds: int = 3600, now=time.time):
        self._ttl = ttl_seconds
        self._now = now
        self._m: dict[str, tuple[TokenClaims, float]] = {}

    def mint(self, claims: TokenClaims) -> str:
        tok = secrets.token_urlsafe(32)
        self._m[tok] = (claims, self._now() + self._ttl)
        return tok

    def resolve(self, token: str) -> ResolvedToken | None:
        rec = self._m.get(token)
        if rec is None:
            return None
        claims, exp = rec
        if self._now() >= exp:
            self._m.pop(token, None)
            return None
        return ResolvedToken(claims.sub, claims.enterprise, claims.role, claims.session)

    def revoke_session(self, session: str) -> int:
        gone = [t for t, (c, _) in self._m.items() if c.session == session]
        for t in gone:
            self._m.pop(t, None)
        return len(gone)
```

- [ ] **Step 4:运行验证通过**

Run: `uv run pytest tests/dev_workspace/test_wstoken.py -q`
Expected: PASS(4 passed)。

- [ ] **Step 5:Commit**
```bash
git add services/gateway/bff/wstoken.py tests/dev_workspace/test_wstoken.py
git commit -m "feat(plan9): BFF 每会话工作区令牌(铸/验/映射 + TTL + 撤销)"
```

---

## Task 3:我们的 MCP server(令牌 → Context → can() 闸)

> http-transport MCP server;令牌从 URL 路径还原 `Context`(与控制台后端同形),所有工具调用前置 `can()` 入口。本 task 只搭骨架 + 身份还原 + 一个受 can() 保护的探活工具;真实数据工具在 Task 4。

**Files:**
- Create: `services/dev_workspace_mcp/__init__.py`(空)
- Create: `services/dev_workspace_mcp/identity.py`
- Create: `services/dev_workspace_mcp/app.py`
- Modify: `pyproject.toml`(加 `mcp` 依赖)
- Test: `tests/dev_workspace/test_mcp_identity.py`

- [ ] **Step 1:加依赖**

Run: `uv add mcp && uv sync --extra dev`
Expected: `mcp` 进 `pyproject.toml`,锁定成功。(若 Task 0 Step 3 记录的 SDK API 名不同,以 RESULTS 为准。)

- [ ] **Step 2:写失败测试(令牌 → Context 还原)**
```python
# tests/dev_workspace/test_mcp_identity.py
from services.gateway.bff.wstoken import WorkspaceTokenStore, TokenClaims
from services.dev_workspace_mcp.identity import context_from_token, set_current_token, current_context
from libs.identity.ids import EnterpriseId

def test_token_resolves_to_context_with_owner_and_enterprise():
    store = WorkspaceTokenStore(now=lambda: 0)
    tok = store.mint(TokenClaims(sub="u-alice", enterprise="ent-demo", role="member", session="s1"))
    ctx = context_from_token(store, tok)
    assert ctx.user == "u-alice"
    assert ctx.role_in(EnterpriseId("ent-demo")) == "member"

def test_unknown_token_yields_none():
    store = WorkspaceTokenStore()
    assert context_from_token(store, "bad") is None

def test_current_context_uses_contextvar(monkeypatch):
    store = WorkspaceTokenStore(now=lambda: 0)
    tok = store.mint(TokenClaims("u-bob", "ent-demo", "enterprise-admin", "s2"))
    set_current_token(store, tok)
    assert current_context().user == "u-bob"
```

- [ ] **Step 3:运行验证失败**

Run: `uv run pytest tests/dev_workspace/test_mcp_identity.py -q`
Expected: FAIL(模块不存在)。

- [ ] **Step 4:实现身份还原**
```python
# services/dev_workspace_mcp/identity.py
# 令牌 → Context(与控制台后端同形,复用 Membership/EnterpriseId)。当前会话令牌用 contextvar
# 承载(FastMCP 工具函数从此读 ctx)。fail-closed:令牌无效 → None,工具按 deny 处理。
from __future__ import annotations
import contextvars
from libs.identity.context import Context, Membership
from libs.identity.ids import EnterpriseId
from services.gateway.bff.wstoken import WorkspaceTokenStore

_token: contextvars.ContextVar[str | None] = contextvars.ContextVar("ws_token", default=None)
_store: contextvars.ContextVar[WorkspaceTokenStore | None] = contextvars.ContextVar("ws_store", default=None)

def context_from_token(store: WorkspaceTokenStore, token: str) -> Context | None:
    r = store.resolve(token)
    if r is None:
        return None
    is_admin = r.role == "enterprise-admin"
    return Context(user=r.sub,
                   memberships=[Membership(EnterpriseId(r.enterprise), r.role)],
                   is_platform_admin=False)   # 工作区会话不走平台管理员特权

def set_current_token(store: WorkspaceTokenStore, token: str) -> None:
    _store.set(store); _token.set(token)

def current_context() -> Context | None:
    s, t = _store.get(), _token.get()
    return context_from_token(s, t) if (s and t) else None
```

- [ ] **Step 5:运行验证通过**

Run: `uv run pytest tests/dev_workspace/test_mcp_identity.py -q`
Expected: PASS(3 passed)。

- [ ] **Step 6:搭 MCP app + 令牌路由包裹 + 探活工具**
```python
# services/dev_workspace_mcp/app.py
# http-transport MCP server。URL 形如 /s/<token>/mcp;包裹层把 token 注入 contextvar(身份绑定),
# 再交给 FastMCP ASGI app。工具调用前置 can()(数据授权唯一出入口,宪法 §2.4)。
from __future__ import annotations
import os
from mcp.server.fastmcp import FastMCP
from libs.authz.engine import can
from libs.authz.types import Resource
from libs.identity.ids import EnterpriseId
from services.gateway.bff.wstoken import WorkspaceTokenStore
from services.dev_workspace_mcp.identity import set_current_token, current_context

STORE = WorkspaceTokenStore(ttl_seconds=int(os.getenv("WS_TOKEN_TTL", "3600")))
mcp = FastMCP("liteai-dev-workspace")

@mcp.tool()
def whoami() -> dict:
    """探活 + 身份回显:证明令牌已绑定为某用户/企业。"""
    ctx = current_context()
    if ctx is None:
        return {"error": "unauthenticated"}        # fail-closed
    ent = ctx.memberships[0].enterprise_id if ctx.memberships else None
    return {"user": ctx.user, "enterprise": str(ent) if ent else None}

def build_asgi(store: WorkspaceTokenStore = STORE):
    inner = mcp.streamable_http_app()
    async def app(scope, receive, send):
        if scope["type"] == "http":
            parts = scope["path"].split("/")
            if len(parts) > 2 and parts[1] == "s":
                set_current_token(store, parts[2])
                scope = dict(scope); scope["path"] = "/" + "/".join(parts[3:])
        await inner(scope, receive, send)
    return app

asgi = build_asgi()
```

- [ ] **Step 7:加 import-linter 合同(分层守护)**

在 `pyproject.toml` 的 import-linter 配置加:`dev_workspace_mcp` 可依赖 `libs.*` 与 `services.gateway.bff.wstoken`,**禁**反向依赖。
Run: `make lint`
Expected: PASS(无违规 import)。

- [ ] **Step 8:Commit**
```bash
git add services/dev_workspace_mcp/ tests/dev_workspace/test_mcp_identity.py pyproject.toml uv.lock
git commit -m "feat(plan9): MCP server 骨架(令牌→Context→can() 闸 + whoami 探活)"
```

---

## Task 4:第一个数据工具 `catalog_read_schema`(can() 把关)

> 让 agent 经令牌化工具读数据集 schema/采样——US2 数据探查的最小落点。复用 metadata 的 Gravitino 读取与 `can()` 模式(`services/metadata_service/app.py`)。

**Files:**
- Create: `services/dev_workspace_mcp/tools/__init__.py`(空)
- Create: `services/dev_workspace_mcp/tools/catalog.py`
- Modify: `services/dev_workspace_mcp/app.py`(注册工具)
- Test: `tests/dev_workspace/test_tool_catalog.py`

- [ ] **Step 1:写失败测试(can() 放行/拒绝)**
```python
# tests/dev_workspace/test_tool_catalog.py
import pytest
from libs.identity.context import Context, Membership
from libs.identity.ids import EnterpriseId
from services.dev_workspace_mcp.tools.catalog import read_schema

class FakeGravitino:
    def __init__(self, fs): self._fs = fs
    def get_fileset(self, ml, cat, sch, name): return self._fs

_OWN = {"name": "coco", "properties": {"owner_user": "u-alice", "scope": "private",
        "format": "webdataset", "num_samples": "5000", "kind": "raw"},
        "storageLocation": "s3a://lite-ai/ent-demo/u-alice/raw/coco/"}

def _ctx(sub, ent="ent-demo"):
    return Context(user=sub, memberships=[Membership(EnterpriseId(ent), "member")])

def test_owner_reads_own_dataset_schema():
    out = read_schema(_ctx("u-alice"), FakeGravitino(_OWN), dataset="coco")
    assert out["format"] == "webdataset" and out["num_samples"] == 5000 and out["owner"] == "u-alice"

def test_non_owner_same_enterprise_denied_private():
    out = read_schema(_ctx("u-eve"), FakeGravitino(_OWN), dataset="coco")
    assert out["error"] == "forbidden"        # can() deny:私有非本人

def test_unattributed_fileset_denied():
    fs = {"name": "x", "properties": {}, "storageLocation": ""}
    out = read_schema(_ctx("u-alice"), FakeGravitino(fs), dataset="x")
    assert out["error"] == "forbidden"        # 不可归属 → fail-closed
```

- [ ] **Step 2:运行验证失败**

Run: `uv run pytest tests/dev_workspace/test_tool_catalog.py -q`
Expected: FAIL(模块不存在)。

- [ ] **Step 3:实现工具(纯函数 + can(),与 metadata_service 同语义)**
```python
# services/dev_workspace_mcp/tools/catalog.py
# 数据探查工具:读 Gravitino fileset 元数据/schema 投影。owner 模型(ADR-024):
# 不可归属 fileset → fail-closed deny;否则 can(dataset.read) 把关(企业硬隔离 + owner)。
# read_schema 为纯函数(ctx + gravitino 注入)→ 可单测;MCP 包装在 app.py。
from __future__ import annotations
from libs.authz.engine import can
from libs.authz.types import Resource
from libs.identity.context import Context
from libs.identity.ids import EnterpriseId
from services._scaffold.auth import enterprise_of

_DENY = {"error": "forbidden"}

def _metalake(ent: str) -> str:
    assert "_" not in ent, ent
    return ent.replace("-", "_")

def read_schema(ctx: Context, gravitino, *, dataset: str,
                catalog: str = "data", schema: str = "datasets") -> dict:
    ent = enterprise_of(ctx)                          # 0/多企业 → 抛(fail-closed)
    try:
        fs = gravitino.get_fileset(_metalake(ent), catalog, schema, dataset)
    except Exception:
        return {"error": "not_found"}
    p = fs.get("properties", {})
    owner = p.get("owner_user")
    if not owner:                                     # 不可归属 → deny
        return _DENY
    res = Resource(kind="dataset", enterprise_id=EnterpriseId(ent),
                   scope=p.get("scope", "private"), owner=owner)
    if not can(ctx, "dataset.read", res).allow:
        return _DENY
    def _int(v):
        try: return int(v)
        except (TypeError, ValueError): return None
    return {"name": fs["name"], "owner": owner, "scope": p.get("scope", "private"),
            "format": p.get("format"), "kind": p.get("kind"),
            "num_samples": _int(p.get("num_samples")),
            "location": fs.get("storageLocation", "")}
```

- [ ] **Step 4:运行验证通过**

Run: `uv run pytest tests/dev_workspace/test_tool_catalog.py -q`
Expected: PASS(3 passed)。

- [ ] **Step 5:把工具接进 MCP server**

在 `services/dev_workspace_mcp/app.py` 加(用真实 Gravitino 客户端,env 配置;复用 metadata 的构造):
```python
from services.metadata_service.gravitino import GravitinoClient   # 复用现有客户端
from services.dev_workspace_mcp.tools.catalog import read_schema as _read_schema
import os

def _gravitino():
    return GravitinoClient(base_url=os.environ["GRAVITINO_URL"])   # 与 metadata 同 env

@mcp.tool()
def catalog_read_schema(dataset: str, catalog: str = "data", schema: str = "datasets") -> dict:
    """探查数据集:返回 owner/scope/format/kind/num_samples/location(经 can() 把关)。"""
    ctx = current_context()
    if ctx is None:
        return {"error": "unauthenticated"}
    return _read_schema(ctx, _gravitino(), dataset=dataset, catalog=catalog, schema=schema)
```
> 注:`GravitinoClient` 构造签名以 `services/metadata_service/gravitino.py` 实际为准(实现时核对;若工厂不同,镜像 metadata_service 的构造方式)。

- [ ] **Step 6:回归 + lint**

Run: `uv run pytest tests/dev_workspace -q && make lint`
Expected: PASS。

- [ ] **Step 7:Commit**
```bash
git add services/dev_workspace_mcp/ tests/dev_workspace/test_tool_catalog.py
git commit -m "feat(plan9): MCP 工具 catalog_read_schema(数据探查 + can() 把关)"
```

---

## Task 5:BFF 工作区会话(建 omnigent 会话 + 铸令牌 + 注册 MCP + header-auth)

> 把链路接起来:用户经 BFF 建工作区会话时,BFF(header-auth 注入身份)在 omnigent 建会话、铸我们的每会话令牌、用令牌化 URL 注册我们的 MCP server。**MUST 剥离客户端伪造的身份头。**

**Files:**
- Create: `services/gateway/bff/omnigent_client.py`
- Create: `services/gateway/bff/workspace.py`
- Test: `tests/dev_workspace/test_bff_workspace.py`

- [ ] **Step 1:写失败测试(omnigent client + 会话装配 + 剥头)**
```python
# tests/dev_workspace/test_bff_workspace.py
import httpx, pytest
from services.gateway.bff.omnigent_client import OmnigentClient

def _client(handler):
    return OmnigentClient(base_url="http://omnigent:8000", email="alice@acme.test",
                          transport=httpx.MockTransport(handler))

def test_create_session_sends_header_auth_and_returns_id():
    seen = {}
    def h(req):
        seen["email"] = req.headers.get("X-Forwarded-Email")
        return httpx.Response(200, json={"id": "sess-omni-1"})
    sid = _client(h).create_session()
    assert sid == "sess-omni-1"
    assert seen["email"] == "alice@acme.test"      # header-auth 注入

def test_register_mcp_sends_tokenized_url():
    seen = {}
    def h(req):
        if req.url.path.endswith("/mcp-servers"):
            import json; seen["body"] = json.loads(req.content)
        return httpx.Response(201, json={})
    _client(h).register_mcp(session_id="sess-omni-1", name="liteai",
                            url="http://liteai-mcp:8000/s/tok-xyz/mcp")
    assert seen["body"]["transport"] == "http"
    assert seen["body"]["url"].endswith("/s/tok-xyz/mcp")
```

- [ ] **Step 2:运行验证失败**

Run: `uv run pytest tests/dev_workspace/test_bff_workspace.py -q`
Expected: FAIL(模块不存在)。

- [ ] **Step 3:实现 omnigent client**
```python
# services/gateway/bff/omnigent_client.py
# omnigent admin REST 薄客户端(header-auth)。仅 BFF 内网调 omnigent;身份经 X-Forwarded-Email
# 注入(omnigent 信任之,故 omnigent 必须不可被客户端直达 + BFF 必须剥离伪造头)。
from __future__ import annotations
import httpx

class OmnigentClient:
    def __init__(self, base_url: str, email: str, header: str = "X-Forwarded-Email",
                 transport: httpx.BaseTransport | None = None):
        self._c = httpx.Client(base_url=base_url.rstrip("/"),
                               headers={header: email}, timeout=30, transport=transport)

    def create_session(self) -> str:
        r = self._c.post("/v1/sessions", json={})
        r.raise_for_status()
        return r.json()["id"]

    def register_mcp(self, *, session_id: str, name: str, url: str) -> None:
        r = self._c.post(f"/v1/sessions/{session_id}/agent/mcp-servers",
                         json={"name": name, "transport": "http", "url": url})
        r.raise_for_status()
```
> 注:`create_session` 的 body/字段、触发 turn 的端点以 **Task 0 RESULTS** 为准(此处用探针实测值;若不同,改这里一处)。

- [ ] **Step 4:实现工作区会话装配(剥头 + 铸令牌 + 注册)**
```python
# services/gateway/bff/workspace.py
# BFF 工作区会话端点:建 omnigent 会话 → 铸每会话令牌 → 注册我们的 MCP server(令牌化 URL)。
# 安全:从【已认证的 BFF 会话】取身份(sub/企业/角色),绝不信任请求里的身份头 —— 反代层 MUST
# 先剥离客户端传入的 X-Forwarded-Email(strip_forged_identity_headers)。
from __future__ import annotations
import os
from services.gateway.bff.wstoken import WorkspaceTokenStore, TokenClaims
from services.gateway.bff.omnigent_client import OmnigentClient

_FORGED = ("x-forwarded-email",)   # 客户端不得自带的信任头(反代入口剥离)

def strip_forged_identity_headers(headers: dict) -> dict:
    return {k: v for k, v in headers.items() if k.lower() not in _FORGED}

def create_workspace_session(*, sub: str, enterprise: str, role: str,
                             store: WorkspaceTokenStore,
                             omni: OmnigentClient, mcp_base_url: str) -> dict:
    sid = omni.create_session()
    tok = store.mint(TokenClaims(sub=sub, enterprise=enterprise, role=role, session=sid))
    omni.register_mcp(session_id=sid, name="liteai",
                      url=f"{mcp_base_url.rstrip('/')}/s/{tok}/mcp")
    return {"session_id": sid}     # 令牌不回给前端(前端不持令牌,经 BFF 反代)
```

- [ ] **Step 5:补测试(剥头 + 装配)**
```python
# 追加到 tests/dev_workspace/test_bff_workspace.py
import httpx
from services.gateway.bff.wstoken import WorkspaceTokenStore
from services.gateway.bff.omnigent_client import OmnigentClient
from services.gateway.bff.workspace import strip_forged_identity_headers, create_workspace_session

def test_strip_forged_identity_header():
    out = strip_forged_identity_headers({"X-Forwarded-Email": "evil@x", "Cookie": "ok"})
    assert "X-Forwarded-Email" not in out and "Cookie" in out

def test_create_workspace_session_binds_token_to_caller():
    calls = {}
    def h(req):
        if req.url.path.endswith("/mcp-servers"):
            import json; calls["url"] = json.loads(req.content)["url"]
            return httpx.Response(201, json={})
        return httpx.Response(200, json={"id": "sess-7"})
    store = WorkspaceTokenStore(now=lambda: 0)
    omni = OmnigentClient("http://omnigent:8000", email="alice@acme.test", transport=httpx.MockTransport(h))
    out = create_workspace_session(sub="u-alice", enterprise="ent-demo", role="member",
                                   store=store, omni=omni, mcp_base_url="http://liteai-mcp:8000")
    assert out["session_id"] == "sess-7"
    tok = calls["url"].rsplit("/", 2)[1]          # /s/<tok>/mcp
    r = store.resolve(tok)
    assert r.sub == "u-alice" and r.enterprise == "ent-demo" and r.session == "sess-7"
```

- [ ] **Step 6:运行验证通过 + lint**

Run: `uv run pytest tests/dev_workspace/test_bff_workspace.py -q && make lint`
Expected: PASS(5 passed)。

- [ ] **Step 7:Commit**
```bash
git add services/gateway/bff/omnigent_client.py services/gateway/bff/workspace.py tests/dev_workspace/test_bff_workspace.py
git commit -m "feat(plan9): BFF 工作区会话(建 omnigent 会话 + 铸令牌 + 注册令牌化 MCP + 剥伪造头)"
```

---

## Task 6:隔离负例 + 端到端受控链路验收(headless runbook)

> 证伪:受控链路在越权/伪造/越界下不破。单测覆盖授权负例;手动 runbook 用真 omnigent 跑通一次"agent 经令牌化工具读 schema"。

**Files:**
- Test: `tests/dev_workspace/test_isolation.py`
- Create: `docs/superpowers/plans/2026-06-26-dev-workspace/RUNBOOK.md`

- [ ] **Step 1:写隔离负例测试(跨企业 / 伪造令牌 / 不可归属)**
```python
# tests/dev_workspace/test_isolation.py
from libs.identity.context import Context, Membership
from libs.identity.ids import EnterpriseId
from services.dev_workspace_mcp.tools.catalog import read_schema
from services.dev_workspace_mcp.identity import context_from_token
from services.gateway.bff.wstoken import WorkspaceTokenStore, TokenClaims

class FakeGravitino:
    def __init__(self, fs): self._fs = fs
    def get_fileset(self, ml, cat, sch, name): return self._fs

_COCO = {"name": "coco", "properties": {"owner_user": "u-alice", "scope": "private",
         "format": "webdataset", "kind": "raw"}, "storageLocation": "s3a://x"}

def _ctx(sub, ent):
    return Context(user=sub, memberships=[Membership(EnterpriseId(ent), "member")])

def test_cross_enterprise_read_denied():
    # 企业 B 的用户读企业 A 的数据集 → metalake 取不到(或 can() 拒)→ 非泄露
    out = read_schema(_ctx("u-bob", "ent-other"), FakeGravitino(_COCO), dataset="coco")
    assert out.get("error")                       # 不返回 coco 的元数据

def test_forged_token_yields_no_context():
    store = WorkspaceTokenStore()
    assert context_from_token(store, "forged-token") is None   # → 工具 unauthenticated

def test_revoked_session_token_denied():
    store = WorkspaceTokenStore(now=lambda: 0)
    tok = store.mint(TokenClaims("u-alice", "ent-demo", "member", "s1"))
    store.revoke_session("s1")
    assert context_from_token(store, tok) is None
```

- [ ] **Step 2:运行验证通过**

Run: `uv run pytest tests/dev_workspace/test_isolation.py -q`
Expected: PASS(3 passed)。

- [ ] **Step 3:写 headless 验收 runbook**

写 `docs/superpowers/plans/2026-06-26-dev-workspace/RUNBOOK.md`,**前置**:`make deps-dev`(KC/MinIO/PG)+ `make bootstrap-catalog`(建桶 + metalake)+ `docker compose -f deploy/dev/omnigent.yml up -d` + 起我们的 MCP server(`uv run uvicorn services.dev_workspace_mcp.app:asgi --port 8910`)。**步骤**(对应 SC-002/SC-003 受控链路):
  1. 经 BFF 建工作区会话(alice)→ 返回 session_id;
  2. 触发 agent turn:"读 coco 的 schema" → 终端/响应见 `catalog_read_schema` 返回 webdataset/5000 + 工具日志含 `can()=allow(ent-demo, owner=u-alice)`;
  3. **负例**:用 alice 会话读 `ent-other` 的数据集 → 被拒(无元数据泄露);
  4. **负例**:直接 `curl` 我们的 MCP server 用伪造 token → unauthenticated;
  5. **负例**:agent 尝试越界写 `/etc/x` → 沙箱拒(Task 0 Step 5 复核)。
  每步带"期望可观察结果"。

- [ ] **Step 4:跑一遍 runbook(人工)**

按 RUNBOOK 执行,勾掉每步;失败走 `superpowers:systematic-debugging`,不假绿。

- [ ] **Step 5:全量门禁 + Commit**

Run: `make test && make lint`
Expected: PASS(全绿)。
```bash
git add tests/dev_workspace/test_isolation.py docs/superpowers/plans/2026-06-26-dev-workspace/RUNBOOK.md
git commit -m "test(plan9): 隔离负例 + headless 受控链路验收 runbook"
```

---

## 后续计划(本计划 de-risk 后再写,各自独立 spec-lite/plan)

- **9b — Dev Workspace 前端**:自建 React19 页(左树 + chat + 文件 + 终端,照高保真原型)+ BFF REST/WS 反代。**依赖 Task 0 RESULTS 的 omnigent WS/turn 端点形态。**
- **9c — 数据工具集 + 管线开发**:`catalog_sample` / `oss_get` / `run_dj`(复用 `pipelines/data_prep`)/ `run_python` / 注册回 catalog;policy:ASK 高成本/危险操作。覆盖 US4。
- **9d — 工作目录持久化 + 本地 git**:对象存储为底、按 workspace 隔离、agent 默认授权;本地 git(init/commit/log);沙箱本地盘 ↔ OSS 同步。覆盖 US5。

---

## Self-Review(对照 spec)

- **Spec 覆盖**:US1(工作台会话)= 9b 前端(本计划出 BFF 会话装配 Task 5);**US2 数据探查 = Task 4 catalog_read_schema** ✓;**US3 隔离承重 = Task 2/3/5/6**(令牌绑定 + can() + 剥头 + 负例)✓;US4 管线 = 9c(显式推迟)；US5 git/持久化 = 9d(显式推迟)。FR-007/008(数据经工具 + can())= Task 3/4 ✓;FR-009 沙箱 = Task 0/1 + runbook ✓;FR-011 无企业 = `enterprise_of` 抛 403(Task 4 继承)✓;FR-012 凭证 env = Task 1/4 ✓。
- **Placeholder 扫描**:无 TBD;每改码步带完整代码;唯二"以实测为准"标注(GravitinoClient 构造、omnigent create_session 字段)均**有 Task 0 RESULTS 决策规则兜底**,非占位。
- **类型一致**:`TokenClaims(sub,enterprise,role,session)` / `ResolvedToken` / `Context(user,memberships)` / `read_schema(ctx, gravitino, *, dataset, catalog, schema)` 全计划一致;令牌 URL 形态 `/s/<token>/mcp` Task 3/5/6 一致。
- **范围**:聚焦后端受控链路一个可独立测试的切片(agent 经令牌+can() 读 schema + 隔离负例),不跨进前端/管线。
