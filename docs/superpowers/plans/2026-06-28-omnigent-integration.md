# Plan 9a — omnigent 集成(对话窗 MVP)Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development(推荐)或 executing-plans 逐 Task 执行。步骤用 `- [ ]` checkbox 跟踪。

**Goal:** 让平台用户经 KC 登录后在 Workspace 对话窗和 omnigent agent 对话(流式),omnigent server+host 容器化自托管、多用户隔离、我们 fork 自编译。**无任何数据访问**(承重墙/MCP/catalog/文件终端 = Plan 9b)。

**Architecture:** omnigent 当按官方方式部署的独立服务用。server 独立容器(deploy/docker `--target runtime`,external-runner)+ postgres;多用户经 `AUTH_PROVIDER=oidc` 接我们 KC;host=managed(server 经我们自写的 `DockerSandboxLauncher` 在自托管 docker 上 provision 隔离容器,SDK harness 进程内跑 agent);omnigent=我们 fork 作 submodule 自编译。前端复用现有 React 对话 UI 经 BFF 反代,前端不持 token。

**Tech Stack:** docker compose;omnigent(我们 fork,submodule,Python/FastAPI);Keycloak OIDC;Python BFF(httpx 反代 REST+WS);React19/Vite 前端。

**决策依据:** [ADR-026](../adr/ADR-026-omnigent-integration.md) · spec=[`2026-06-28-omnigent-integration/spec.md`](./2026-06-28-omnigent-integration/spec.md) · design=[同目录/design.md](./2026-06-28-omnigent-integration/design.md)

---

## ⚠️ 探查优先 + 阶段门(必读)

**Phase 0 = 探针 P1(地基,9a 最大风险),必须先跑通并由 owner 研判,再铺开 Phase 1+。** 上一轮失败正卡在"managed 沙箱在自托管 docker 怎么落地 + agent 在容器里出不来"。这次先用**官方 managed 流程**端到端实测,把这条链路钉死,再做工程化。

复用源:备份分支 `dev-workspace-containerization`(`git show dev-workspace-containerization:<path>` 可取):`scripts/omnigent_build.sh`、omnigent patch 里的 docker launcher 雏形、前端 `AgentChat.tsx`/`useSessionStream.ts`、BFF omnigent 反代骨架。

---

## File Structure(改动地图)

| 文件 | 责任 | 动作 |
|---|---|---|
| `third_party/omnigent`(submodule)| 我们的 omnigent **fork**(模型 C),钉 commit | Create(submodule add 我们 fork)|
| fork: `omnigent/onboarding/sandboxes/docker.py` | `DockerSandboxLauncher`(managed 外层沙箱 = docker 容器)| Create(在 fork 里 commit)|
| fork: `omnigent/server/managed_hosts.py` + `sandboxes/__init__.py` | 注册 `provider: docker` | Modify(fork)|
| `scripts/omnigent_build.sh` | 从 submodule 自编译 server+host 两镜像 | Create(捞备份)|
| `deploy/dev/omnigent/docker-compose.yml` | server(runtime)+ postgres,KC OIDC env,`sandbox: provider: docker` | Create |
| `deploy/dev/keycloak/realm-lite-ai.json` | 注册 omnigent OIDC client | Modify |
| `services/gateway/bff/omnigent_proxy.py` | BFF 反代 omnigent REST+WS,注入身份 + 剥伪造头 | Create |
| `services/gateway/bff/middleware.py` | 挂载反代路由 | Modify |
| `frontend/src/pages/Workspace.tsx` + `devws/AgentChat.tsx`/`useSessionStream.ts` | 对话窗(捞备份)| Create |
| `frontend/src/api/omnigent.ts` | 前端→BFF 客户端(建会话/发消息/SSE)| Create |
| `Makefile` / `scripts/dev_services.sh` | 起停 omnigent 栈 | Modify |
| `docs/.../2026-06-28-omnigent-integration/RUNBOOK.md` | 手动验收 | Create |

---

## Phase 0 — 探针 P1(GATE:先跑通 + owner 研判)

### Task 0:官方 managed 链路在自托管 docker 上端到端跑通(含最小 DockerSandboxLauncher)

**目标(可证伪):** 一个 KC 用户经 omnigent(容器化 server)发消息 → server 经我们的 `DockerSandboxLauncher` 在本机 docker 拉起隔离容器 host → SDK harness 起 agent → **流式回复**回到 SSE。产出:① 能跑的 server 容器 + KC OIDC ② 最小可用 docker launcher ③ 实测的端点/事件/凭据注入事实成文。

**Files:**
- Create: `docs/superpowers/plans/2026-06-28-omnigent-integration/spikes/P1-managed-docker.md`(实测结论)
- Create(throwaway-ok,后续 Task 2/3 正式化): 临时 fork + compose + launcher

- [ ] **Step 1: fork omnigent 到我们仓 + 本地 clone 作 submodule(临时也行)**

```bash
cd /Users/yanwen/Documents/github/lite-ai-infra
# 若已有 third_party/omnigent 残留(备份遗留),先确认其上游 ref;否则:
git submodule add <我们的 omnigent fork git url> third_party/omnigent   # 模型C:fork 仓
# 临时:也可先用残留的 third_party/omnigent(38523a1)验证可行性,P1 通过后再正式 fork
git -C third_party/omnigent log -1 --format='%h %s'
```
Expected: third_party/omnigent 就位(我们 fork 或临时上游 ref)。

- [ ] **Step 2: 读官方 deploy/docker + managed_hosts,确认 P1 所需的真实配置/接口**

```bash
sed -n '1,60p' third_party/omnigent/deploy/docker/docker-compose.yaml
sed -n '1,40p' third_party/omnigent/deploy/docker/README.md
grep -nE "launcher_factory|ManagedSandboxConfig|create_app|sandbox_config" third_party/omnigent/omnigent/server/app.py third_party/omnigent/omnigent/server/managed_hosts.py | head
```
记录:server 起法、OIDC env 名、`create_app(sandbox_config=...)` 怎么传自定义 launcher、SDK harness 怎么选(agent spec executor.harness=claude-sdk/openai-agents)、模型凭据怎么经 sandbox env 注入。写进 `spikes/P1-managed-docker.md`。

- [ ] **Step 3: 写最小 DockerSandboxLauncher(在 fork 里)**

参照备份分支雏形:`git show dev-workspace-containerization:deploy/omnigent-patches/0004-docker-sandbox-launcher.patch`。在 fork 实现 `omnigent/onboarding/sandboxes/docker.py` 的 `DockerSandboxLauncher(SandboxLauncher)`:`prepare`(docker version)/`provision(name)`(`docker run -d` host 容器,返回容器 id)/`run`(`docker exec`)/`put`(`docker cp`)/`terminate`(`docker rm -f`)。token+凭据经 base `start_host` 的 exec env 注入(不进 `docker run` argv)。在 `managed_hosts.py` 注册 `provider: docker`(`SUPPORTED_SANDBOX_PROVIDERS` + `PROVIDERS_WITH_MANAGED_LAUNCH` + `parse_sandbox_config` 分支 + factory)。

- [ ] **Step 4: 构建镜像 + 起 server(容器化,KC OIDC,sandbox=docker)**

```bash
scripts/omnigent_build.sh dev   # 编译 omnigent-server:dev + omnigent-host:dev(带我们的 docker launcher)
# 起 server + postgres,配 KC OIDC + sandbox provider=docker(挂 /var/run/docker.sock 让 server 能 docker run)
docker compose -f deploy/dev/omnigent/docker-compose.yml up -d
curl -s localhost:8900/api/version
```
Expected: server 起来;`docker run --rm omnigent-host:dev python -c "import omnigent.onboarding.sandboxes.docker"` 不报错。

- [ ] **Step 5: 端到端实测(KC 登录 → 建会话 → managed 沙箱 → SDK agent → 流式)**

用 KC 的 alice 走 OIDC 登录 omnigent(或经 BFF;P1 可先直连 server 验证),建一个 host_type=managed 会话,发消息,确认:① server 经 DockerSandboxLauncher `docker run` 了一个 host 容器(`docker ps` 看到)② agent(SDK harness)回复 ③ 回复**流式**到达(SSE 有增量事件)④ 模型凭据经 sandbox env 注入生效。把真实端点/SSE 事件类型/凭据注入方式记进 `spikes/P1-managed-docker.md`。

- [ ] **Step 6: 写结论 + 决策,commit**

`spikes/P1-managed-docker.md` 写:跑通与否 + 实测事实(端点/事件/凭据/隔离)+ **决策**(跑通→Phase 1+ 按此正式化;某处不通→改我们 fork 里的 launcher 再试;实在不行→退 k8s pod provider 或 BYO,回 design)。
```bash
git add docs/superpowers/plans/2026-06-28-omnigent-integration/spikes/ third_party/omnigent deploy/dev/omnigent scripts/omnigent_build.sh
git commit -m "spike(9a): P1 官方 managed+docker 链路端到端实测 + 最小 DockerSandboxLauncher"
```

> **★ 阶段门**:Task 0 跑通 → owner 研判 spikes/P1-managed-docker.md → 确认 Phase 1+ 方向 → 继续。**不通则不铺开后续。**

---

## Phase 1 — omnigent fork 自构建固化(模型 C)

### Task 1:omnigent fork 作 submodule + 自编译两镜像

**Files:**
- Create/Modify: `.gitmodules`、`third_party/omnigent`(指我们 fork 的钉定 commit)
- Create: `scripts/omnigent_build.sh`(若 Task0 用的是临时版,这里正式化)
- Modify: `pyproject.toml`(pytest 排除 `third_party`,沿用备份做法)

- [ ] **Step 1: 正式 fork + submodule 钉定**

确保 `third_party/omnigent` 指向**我们的 fork 仓**的某 commit(含 Task0 的 DockerSandboxLauncher)。`.gitmodules` 记录 fork url。

- [ ] **Step 2: 构建脚本正式化**

`scripts/omnigent_build.sh`(捞备份分支版,去掉 patch-queue 逻辑——模型 C 直接从 fork build):
```bash
# dev: docker build --target runtime -t omnigent-server:dev;--target host -t omnigent-host:dev
# ci: buildx --push 到 registry(release tag);prod pull same-bits
```

- [ ] **Step 3: pytest 排除 third_party**

`pyproject.toml` 的 `[tool.pytest.ini_options]` 加 `addopts = "... --ignore=third_party"` + `norecursedirs = ["third_party"]`(捞备份)。
Run: `uv run pytest -q` → 不收集 third_party 的测试,既有测试仍绿。

- [ ] **Step 4: Commit**
```bash
git add .gitmodules third_party/omnigent scripts/omnigent_build.sh pyproject.toml
git commit -m "build(9a): omnigent fork 作 submodule + 自编译 server/host 镜像(模型C)"
```

---

## Phase 2 — server 容器化部署 + KC OIDC 多用户

### Task 2:omnigent server compose(runtime)+ postgres + KC OIDC

**Files:**
- Create: `deploy/dev/omnigent/docker-compose.yml`
- Modify: `deploy/dev/keycloak/realm-lite-ai.json`(注册 omnigent OIDC client)
- Modify: `Makefile`(omnigent-up/down)

- [ ] **Step 1: KC 注册 omnigent client**

`realm-lite-ai.json` 加一个 confidential client `omnigent`(redirectUris=omnigent server 的 `/auth/callback`,标准 OIDC)。

- [ ] **Step 2: server compose**

`deploy/dev/omnigent/docker-compose.yml`:postgres + omnigent server(`omnigent-server:dev`),env:
```yaml
DATABASE_URL: postgresql+psycopg://...
OMNIGENT_AUTH_ENABLED: "1"
OMNIGENT_AUTH_PROVIDER: oidc
OMNIGENT_OIDC_ISSUER: http://<kc>/realms/lite-ai
OMNIGENT_OIDC_CLIENT_ID: omnigent
OMNIGENT_OIDC_CLIENT_SECRET: <secret>
OMNIGENT_OIDC_REDIRECT_URI: http://<server>/auth/callback
OMNIGENT_OIDC_COOKIE_SECRET: <hex32>
# sandbox provider=docker(Task0/3 的 launcher);挂 docker.sock
sandbox: {provider: docker, server_url: http://<server>}
volumes: ["/var/run/docker.sock:/var/run/docker.sock"]
```
(精确 env 名以 P1 实测为准。)

- [ ] **Step 3: 起 + 验证多用户登录**

`make omnigent-up` → KC alice 登录 omnigent OIDC 通;bob 登录得到独立身份。
Expected: 两用户各自 session,server 认得身份。

- [ ] **Step 4: Commit**
```bash
git add deploy/dev/omnigent deploy/dev/keycloak/realm-lite-ai.json Makefile
git commit -m "feat(9a): omnigent server 容器化 + KC OIDC 多用户"
```

---

## Phase 3 — DockerSandboxLauncher 硬化(在 fork)

### Task 3:managed 沙箱 docker launcher 健壮化 + 隔离/回收

**Files:**
- Modify(fork): `omnigent/onboarding/sandboxes/docker.py`
- Test: fork 内单测 或 我们仓 `tests/omnigent_integration/test_docker_launcher_contract.py`(轻量:断言 provider 注册 + launcher 签名一致)

- [ ] **Step 1: 硬化 launcher**

基于 P1 雏形补:容器命名 per (owner,session)、`docker rm -f` 幂等回收、host 容器加资源限制/网络隔离、产品凭据经 env 注入、失败清理。确保 `DockerSandboxLauncher.__abstractmethods__ == frozenset()`(签名对齐 base)。

- [ ] **Step 2: 轻量契约测试(我们仓,守 patch/fork 不退化)**

`tests/omnigent_integration/test_docker_launcher_contract.py`:`docker run --rm omnigent-server:dev python -c "from omnigent.server.managed_hosts import SUPPORTED_SANDBOX_PROVIDERS as P; assert 'docker' in P"` 包成 pytest(或 skip if no docker)。
Run: `uv run pytest -q tests/omnigent_integration/` → PASS。

- [ ] **Step 3: 回归构建 + commit(fork commit + bump submodule)**
```bash
scripts/omnigent_build.sh dev
git -C third_party/omnigent commit -am "feat(docker-launcher): 硬化隔离/回收/凭据注入"
git add third_party/omnigent tests/omnigent_integration
git commit -m "feat(9a): DockerSandboxLauncher 硬化 + 契约测试"
```

---

## Phase 4 — BFF 反代 omnigent(REST + WS)

### Task 4:BFF 反代 + 身份注入 + 剥伪造头

**Files:**
- Create: `services/gateway/bff/omnigent_proxy.py`
- Modify: `services/gateway/bff/middleware.py`
- Test: `tests/gateway/bff/test_omnigent_proxy.py`

- [ ] **Step 1: 失败测试**

`test_omnigent_proxy.py`:① 未认证 → 反代路由 401 ② 认证后请求被注入身份头、客户端伪造的同名头被剥离 ③ WS/SSE 流式透传(用 MockTransport 验转发 + 头处理)。捞备份 `dev-workspace-containerization:services/gateway/bff/workspace_routes.py` 的反代/剥头模式。

- [ ] **Step 2: 跑失败 → 实现 omnigent_proxy + 挂载 → 跑通**

`make_omnigent_router(*, claims, omni_base_url, send_identity)`:`POST /v1/ws/sessions`(建会话)、`POST .../turn`(发消息)、`GET .../stream`(SSE 透传)、WS 透传(如需)。身份取自已认证 BFF 会话(`_resolve`),剥伪造头。`middleware.py` 挂载。
Run: `uv run pytest -q tests/gateway/bff/test_omnigent_proxy.py` → PASS。

- [ ] **Step 3: Commit**
```bash
git add services/gateway/bff/omnigent_proxy.py services/gateway/bff/middleware.py tests/gateway/bff/test_omnigent_proxy.py
git commit -m "feat(9a): BFF 反代 omnigent REST+WS + 身份注入 + 剥伪造头"
```

---

## Phase 5 — 前端对话窗(复用现有 UI)

### Task 5:Workspace 对话窗接入

**Files:**
- Create: `frontend/src/pages/Workspace.tsx`、`frontend/src/pages/devws/AgentChat.tsx`、`useSessionStream.ts`、`frontend/src/api/omnigent.ts`
- Modify: 前端路由/导航(加 Workspace 菜单)
- Test: `frontend/src/pages/devws/{AgentChat,useSessionStream}.test.tsx`

- [ ] **Step 1: 捞备份组件**
```bash
git show dev-workspace-containerization:frontend/src/pages/devws/AgentChat.tsx > frontend/src/pages/devws/AgentChat.tsx
git show dev-workspace-containerization:frontend/src/pages/devws/useSessionStream.ts > frontend/src/pages/devws/useSessionStream.ts
# 同样捞测试;按 9a 调整(useSessionStream 走 P1 实测的 SSE delta 事件;含中文 IME !isComposing 修复)
```

- [ ] **Step 2: api/omnigent.ts + Workspace 页 + 路由**

`api/omnigent.ts`:`createSession()`/`sendTurn(id,text)`/SSE 消费(经 BFF `/v1/ws/...`,CSRF 双提交,前端不持 token)。`Workspace.tsx` 组合 AgentChat。加导航菜单项。

- [ ] **Step 3: 前端测试 + lint + build**
```bash
cd frontend && npx vitest run src/pages/devws/ && npm run lint && npm run build
```
Expected: 绿。

- [ ] **Step 4: Commit**
```bash
git add frontend/src
git commit -m "feat(9a): Workspace 对话窗(复用对话 UI,经 BFF 反代)"
```

---

## Phase 6 — 编排 + 手动验收

### Task 6:一键起栈 + 双用户验收 runbook

**Files:**
- Modify: `Makefile`(ws-up:omnigent server + 我们服务 + 前端)
- Create: `docs/superpowers/plans/2026-06-28-omnigent-integration/RUNBOOK.md`

- [ ] **Step 1: ws-up 编排**

`Makefile ws-up`:build omnigent 镜像 → 起 omnigent server compose(KC OIDC + docker sandbox)→ 起我们服务(gateway 等)→ 前端。`ws-down` 全停。

- [ ] **Step 2: 全量门禁**
```bash
uv run pytest -q && uv run lint-imports && bash scripts/ci_guards.sh
cd frontend && npm run lint && npx vitest run && npm run build
```
Expected: 全绿。

- [ ] **Step 3: 手动验收 runbook(写入 + 实跑)**

可证伪(对齐 spec SC):
1. `make ws-up`;alice 登录控制台 → Workspace → 发消息 → **回复流式出现**(SC-002)。
2. bob 另登 → 各自会话;**alice 列表无 bob 会话;alice 越权访问 bob 会话/host 被拒**(SC-003,隔离负向)。
3. `docker ps` 看到 alice/bob 各自的 managed host 容器(外层隔离)。
4. **改 omnigent fork 一行**(如回复加个前缀)→ `scripts/omnigent_build.sh dev` → 重起 → 改动生效(SC-004,模型 C)。
5. parity:`docker images | grep omnigent`(dev 跑的是自编译镜像,非上游)。
6. 负向:伪造 X-Forwarded-* 经前端到不了 omnigent;未登录访问 Workspace 跳登录。

- [ ] **Step 4: Commit**
```bash
git add Makefile docs/superpowers/plans/2026-06-28-omnigent-integration/RUNBOOK.md
git commit -m "feat(9a): ws-up 编排 + 双用户对话验收 runbook"
```

---

## DoD(完成定义)
- [ ] Task 0 探针跑通 + owner 研判(官方 managed+docker 链路端到端,含 SDK harness 流式)
- [ ] omnigent server 独立容器 + KC OIDC 多用户登录
- [ ] host=managed:server 经 DockerSandboxLauncher 在自托管 docker 拉隔离容器,用户间隔离(双用户互不可见 + 越权被拒,负向测试绿)
- [ ] agent SDK harness 流式回复(对话窗渐进出现)
- [ ] omnigent = 我们 fork 自编译(改一行→重编译→生效);dev/prod 同源 parity
- [ ] 9a **无数据访问**(无 MCP/can()/catalog/文件终端)
- [ ] `make test` + `make lint` + 前端 lint/test/build 全绿
- [ ] 双用户 live 验收 runbook 通过

## 显式不做(Plan 9b)
左树 catalog/git、文件 monaco/终端 xterm、MCP 数据工具 + 企业/owner `can()` 承重墙、Data-Juicer 管线、工作目录 OSS 持久化、个人订阅模型凭据评估。
