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

## Phase 2 — server 容器化部署 + header-trust 多用户(KC OIDC 在 BFF)

> **★ 探针补漏修订(2026-06-29,ADR-026 §3 已更新)**:omnigent 用 **header-trust** 模式(`AUTH_PROVIDER=header`),**不**在 omnigent 端跑 OIDC。理由:omnigent `oidc` 模式会让浏览器二次登录 + 持有 omnigent `ap_session` cookie(撞 FR-008)。KC OIDC **仍在,落在 BFF**(已实现);BFF 用已认证 KC 会话注入 `X-Forwarded-Email` 给 omnigent、剥伪造头(= Task 4)。**故 plan 原 Step 1「KC 注册 omnigent OIDC client」取消**(header 模式不需要;非静默砍——见此注 + ADR-026 §3)。

### Task 2(=T3):omnigent server compose(runtime)+ postgres + header-trust

**Files:**
- Modify: `deploy/dev/omnigent/docker-compose.yml`(探针级 → 正式化:header-trust 多用户 + `:dev` 镜像)
- Modify: `deploy/dev/omnigent/config.yaml`(如需:固化默认 agent / sandbox)
- Modify: `Makefile`(omnigent-up/down)
- ~~Modify: `realm-lite-ai.json`~~ **取消**(header 模式不需 omnigent OIDC client)

- [ ] **Step 1: pin 默认 agent_id 来源**

managed 建会话需 `agent_id`(`POST /v1/sessions {agent_id,host_type:managed}`)。探查运行中的 server:用 `GET /v1/agents`(内置 agent 发现)拿默认 agent,或在 server 启动/config 注册一个默认 agent。把"前端/BFF 怎么拿到一个可用 agent_id"钉死成事实(写进 compose 注释或 spike 附注)。

- [ ] **Step 2: server compose 正式化(header-trust)**

`deploy/dev/omnigent/docker-compose.yml`:postgres + omnigent server(`omnigent-server:dev`,**非 `:probe`**),env(env 名源码已核实,见 ADR-026 §3 / Explore 报告):
```yaml
DATABASE_URL: postgresql+psycopg://...
OMNIGENT_AUTH_ENABLED: "1"
OMNIGENT_AUTH_PROVIDER: header
OMNIGENT_AUTH_HEADER: X-Forwarded-Email      # omnigent 信任的身份头(BFF 注入)
OMNIGENT_CONFIG: /config.yaml
CLAUDE_CODE_OAUTH_TOKEN: ${CLAUDE_CODE_OAUTH_TOKEN:?}   # 仅订阅 token,勿混 ANTHROPIC_API_KEY
# sandbox provider=docker(P1 launcher);挂 docker.sock
volumes: ["/var/run/docker.sock:/var/run/docker.sock", "./config.yaml:/config.yaml:ro"]
```

- [ ] **Step 3: 起 + 验证多用户隔离(live,无需 KC)**

`make omnigent-up` → 用 `X-Forwarded-Email: alice@test` 建会话/发消息;用 `X-Forwarded-Email: bob@test` 另一身份。
Expected: 两身份各自 session + 各自 managed host 容器(`docker ps` 两个);alice 列表无 bob 会话;alice 拿 bob session_id 越权被拒(owner 校验)。**header 模式让 T3 可脱离 KC 独立 live 验证隔离。**

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

## Phase 3.5 — fork 修 runner_tunnel(多用户 auth 下 managed runner 回连)

### Task 3.5(=T3.5,fork):runner_tunnel 加 managed-token 旁路

> **★ 探针补漏(2026-06-29,T3 实测 auth 开启后发现,ADR-026 探针结论已记)**:多用户 auth 开启时,自托管 docker managed 的 runner 回连 `runner_tunnel` 被 403(无 host_tunnel 那样的 token 旁路)。不修则 agent 回不了复(破 FR-002)。**与 header/oidc 无关**(任何 auth-on 都炸)。owner 拍板 = fork 修。

**Files:**
- Modify(fork): `third_party/omnigent/omnigent/server/routes/runner_tunnel.py`(加 managed-token 旁路,镜像 `host_tunnel.py:139-151` 模式)
- 如需:fork runner 侧 env 转发(`omnigent/host/connect.py` / `runner/_entry.py`)让 runner 带上可解析 owner 的 token
- Test(fork):runner_tunnel auth 单测(token 旁路命中 → owner 解出、不 403;无 token 且无身份头 → 仍拒)
- Modify: `third_party/omnigent`(submodule 指针 bump)+ 重编译 `omnigent-server:dev`

- [ ] **Step 1: fork 改 runner_tunnel**:binding-token 已能解出 runner_id(`runner_tunnel.py:286-305`)→ 由 runner→session→owner 服务端解出 owner,绕身份头(managed 场景);非 managed/无效 token 仍走原认证。循 host_tunnel 既有模式。
- [ ] **Step 2: fork TDD 测试**:覆盖旁路命中/未命中两路。`uv run pytest`(在 fork 内或我们仓契约测试)。
- [ ] **Step 3: 重编译 + bump**:`scripts/omnigent_build.sh dev` → fork commit → bump submodule 指针。
- [ ] **Step 4: 重跑 T3 live(auth ON,agent 真回复)**:alice 发消息 → runner ONLINE(无 403)→ claude-native 流式回复 → SSE 收到 `response.output_text.delta`;bob 隔离仍成立。证据成文。
- [ ] **Step 5: Commit**(fork commit + 我们仓 bump + 证据)。

> **★ T3.5/T3.6 实测 + 独立审查结果(2026-06-29)**:fork 修分两处——① WS tunnel(`runner_tunnel.py` managed-token 旁路,fork `8322b356`)② REST + runner 侧(sessions 路由 binding-token→owner 回退 + runner `_make_auth_token_factory` 折入 binding token 作末位凭据,fork `2c4c36a1`)。**根因比预想深**:runner 有 6 个 `_runner_auth` + claude-native forwarder 都经 `_make_auth_token_factory`,故回退必须放该唯一 chokepoint(非仅 server_client)。**live 实测(header-trust,auth ON)**:alice→HELLO_9A、bob→BOB_OK 各自隔离容器、流式 `response.output_text.delta`(Red\nGreen\n/Blue)、零 401、跨用户 404。fork 测试 90/90 绿。**独立安全审查 = APPROVE-WITH-NITS**(7 项不变式逐一对抗式确认:fail-closed/不可伪造/present-identity-wins/managed 门控/无递归/blast-radius 受限/纯增量)。
> **附带修**:host Dockerfile 的 antigravity `agy` 版本钉(1.0.10)随上游漂到 1.0.13 会硬失败——9a 不用 antigravity,改为非致命 WARNING(fork `b4f9d778`),否则每次 host 重编译都被无关 harness 卡住(破 parity)。
> **遗留 Minor(非阻塞,审查建议,记此不静默)**:① REST `_binding_token_owner` 的 owner 查 DB 在事件循环同步执行(WS 路径用 `asyncio.to_thread`);改 async 需把 `_get_user_id`/`_require_user` 及 ~13 调用点改 async,MVP 阶段不划算 → 推迟。② 缺一条"external host(sandbox_provider=None)的 bound runner_id 被 `_resolve_managed_runner_owner` 拒"的直接单测(门控已被审查确认正确 + unknown-token 已覆盖,仅间接覆盖此分支)→ 推迟(无简单 external-host 建表 API)。

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
- [x] Task 0 探针跑通 + owner 研判(官方 managed+docker 链路端到端,含 harness 流式)
- [x] omnigent server 独立容器 + **header-trust** 多用户(KC OIDC 在 BFF;非 omnigent oidc —— 见 ADR-026 §3 修订)
- [x] host=managed:server 经 DockerSandboxLauncher 在自托管 docker 拉隔离容器,用户间隔离(双用户各自容器 + 越权 404,live 实测;负向测试绿)
- [x] agent claude-native 流式回复(`response.output_text.delta` 实测 Red\nGreen\n/Blue;对话窗渐进出现)
- [x] omnigent = 我们 fork 自编译(T3.x 多次改 fork→重编译→生效已证);dev/prod 同源 parity(`:dev` 自编译镜像)
- [x] 9a **无数据访问**(无 MCP/can()/catalog/文件终端 —— 最终交叉审查确认无 9b 渗入,且有守卫测试)
- [x] `make test`(251 passed) + `make lint`(lint-imports KEPT + ci_guards exit 0) + 前端 lint/test(50)/build 全绿(独立复跑确认)
- [ ] 双用户 live 验收 runbook 通过 —— **runbook 已写(owner-readable);执行者代跑步骤(4 沙箱容器 / 5 改码生效 / 6 负向 curl)已实测;steps 1~3 浏览器双用户隔离 = owner 亲自验收(constitution §3.4 ⑤,待 owner)**

## 完成状态(2026-06-29)
**全部实现 + 逐任务独立审查 + 最终交叉审查 = SHIP。** 六任务(T3 compose / T3.5 runner-tunnel fork / T3.6 runner-auth fork / T4 BFF 反代 / T5 前端 / T6 编排+runbook)均 done + reviewed + gate 绿。两道闸:**① 独立 code review 已完成**(T3.5/T3.6 安全 7 不变式对抗式确认 APPROVE-WITH-NITS、T4 trust-boundary APPROVE-WITH-NITS、T5 APPROVE-WITH-NITS、最终交叉审查 SHIP);**② owner 照 runbook 双用户浏览器验收 = 待 owner**(合并前最后一闸)。
**遗留 Minor(非阻塞,记此不静默)**:① BFF turn content block 发 `{type:"text"}`,omnigent 规范 user 类型是 `input_text`——**实测 `text` 一路可用**(server 按 `text` 字段取值,不卡 type),改 `input_text` 属规范对齐但 input 侧未实测,故保留已证路径、仅记。② T3.6 REST owner 查 DB 在事件循环同步(WS 用 to_thread)——改 async 需传染 ~13 调用点,MVP 不划算。③ T5 跨会话 in-flight fetch race(React19 下良性,~400ms 自纠)。

## 显式不做(Plan 9b)
左树 catalog/git、文件 monaco/终端 xterm、MCP 数据工具 + 企业/owner `can()` 承重墙、Data-Juicer 管线、工作目录 OSS 持久化、个人订阅模型凭据评估。
