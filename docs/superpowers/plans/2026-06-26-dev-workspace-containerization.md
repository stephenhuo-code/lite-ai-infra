# Dev Workspace 全容器化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Dev Workspace 的 omnigent 后端从「dev host 跑 native 源码 + 单用户」演进为「全容器化 + header-auth 多用户 + per-user managed host + 真流式」,恢复 dev/prod parity(§5.3),消除技术债。

**Architecture:** omnigent server(容器,header-auth 多用户)+ per-user managed host(容器,携带该用户 claude/codex 订阅凭据,一 host 多 session)+ runner(每会话动态派生,sandbox=none〔显式推迟〕)。承重墙不变:BFF 铸令牌→我们的 MCP `can()`→数据,与 omnigent 身份正交。

**Tech Stack:** docker compose(dev)/ 镜像同 prod;omnigent(vendored `third_party/omnigent` + patch-queue `deploy/omnigent-patches/`);Python(BFF/MCP,FastAPI + httpx + cryptography Fernet);React19/Vite(前端 SSE 流式)。

**决策依据:** [ADR-027](../adr/ADR-027-dev-workspace-full-containerization.md)(承接 [ADR-026](../adr/ADR-026-dev-workspace-omnigent.md));设计:[design-containerization.md](./2026-06-26-dev-workspace/design-containerization.md)。

---

## ⚠️ 探查优先 + 阶段门(必读)

本计划有**两个 DoR 标记的探针,gate 后续阶段**。**Phase 0 必须先跑完并由 owner 研判**,再进 Phase 3/4:

- **P1(地基风险,gate Phase 3)**:omnigent 在我们 infra(docker on ECS)上 server-launch per-user managed host 是否可行?现成 provider 多为云沙箱(Modal/Daytona/CoreWeave/OpenShell),我们可能要**自写一个 docker provider**,或退到**「我们侧编排预起 per-user host 容器 + 静态注册」**。
- **P2(gate Phase 4)**:容器化 server-launched 路径下,流式 delta(codex 逐 token / claude 段落级)是否真达 SSE `/stream`?

**决策规则**写在 Task 0a/0b 里。Phase 1/2 与探针**无关**,可并行先做。

---

## File Structure(改动地图)

| 文件 | 责任 | 动作 |
|---|---|---|
| `deploy/omnigent-patches/0001-claude-native-inject-session-mcp.patch` | 把现有 omnigent 工作树补丁(claude-native 注入会话 MCP)固化进 patch-queue | Create |
| `deploy/omnigent-patches/0002-add-python-socks.patch` | python-socks 依赖(SOCKS 代理 tunnel) | Create |
| `deploy/dev/omnigent.yml` | omnigent server compose;开 header-auth、加容器化 host service | Modify |
| `deploy/dev/omnigent-host.yml` | 容器化 host(用 omnigent-host 镜像)compose | Create |
| `libs/config/__init__.py` | 加 `omnigent.auth_enabled` 等 dev/prod 差异配置 | Modify |
| `services/credential_vault/` | per-user 订阅凭据加密存储(Fernet)+ 取/存/删 | Create |
| `services/gateway/bff/credentials_routes.py` | onboarding API:提交/查状态/删订阅凭据 | Create |
| `frontend/src/pages/devws/ModelCredentials.tsx` | 「连接订阅」设置页(第一个消费者,低保真) | Create |
| `services/gateway/bff/managed_host.py` | per-user host:确保在线(launch if absent)+ 注入凭据 | Create |
| `services/gateway/bff/workspace.py` | 建会话先确保该用户 host,再 launch_runner | Modify |
| `frontend/src/pages/devws/useSessionStream.ts` | 增量流式(delta)渲染 + items 兜底 | Modify |
| `scripts/dev_services.sh` / `Makefile` | `ws-up` 用容器化 host(退役 native ws-host-up 为快验别名) | Modify |

---

## Phase 0 — 探查优先(GATE,先跑 + owner 研判)

### Task 0a(P1): per-user managed host 在我们 infra 上的 launch 机制探针

**Files:**
- Create: `docs/superpowers/spikes/2026-06-27-managed-host-provider/probe.md`(实测结论 + 决策)

- [ ] **Step 1: 读 omnigent managed-host provider 源码,列可选 provider**

Run:
```bash
cd /Users/yanwen/Documents/github/lite-ai-infra/third_party/omnigent
grep -rniE "provider|managed.*host|launch.*sandbox|modal|daytona|coreweave|openshell|docker.*run|provider.*registry" omnigent/server/managed_hosts.py omnigent/server/ 2>/dev/null | grep -iE "provider|launch|docker|kubernetes|k8s" | head -40
```
Expected: 列出 omnigent 内置 provider 名 + 注册点;判断有无 docker/local provider。

- [ ] **Step 2: 起容器化 server(header-auth),尝试 server-launch managed host**

Run(用 host 镜像 + 现成 provider 配置,具体 env 由 Step1 结论填):
```bash
cd /Users/yanwen/Documents/github/lite-ai-infra
scripts/omnigent_build.sh dev               # 确保 omnigent-host:dev 在本地
# 按 Step1 找到的 provider 配置启 server,调 server 的 managed-host launch API/CLI 起一个 host
curl -s -X POST localhost:8900/v1/hosts/managed -H 'X-Forwarded-Email: probe@acme.test' -d '{...}'   # 端点名以 Step1 源码为准
```
Expected: 要么 server 成功拉起一个 host 容器并注册 online,要么明确报"无可用 provider"。

- [ ] **Step 3: 记录结论 + 决策(probe.md)**

写入 `probe.md`,按**决策规则**判定走哪条:
- **(a) 有可用 docker/local provider** → 配置之,Phase 3 用 omnigent 原生 managed-host launch。
- **(b) 无,但自写 docker provider 成本低** → Phase 3 加一个最小 docker provider(`docker run omnigent-host` + 注入 host token/凭据)。
- **(c) 自写成本高** → **退到「我们侧编排」**:BFF/小编排器 `docker run` per-user host 容器(dev)/ k8s(prod),host 用 `OMNIGENT_HOST_TOKEN` 注册到 server。Phase 3 按此实现(本计划 Phase 3 默认按 (c) 写,最不依赖 omnigent 内部;(a)/(b) 命中则简化)。

- [ ] **Step 4: Commit**
```bash
git add docs/superpowers/spikes/2026-06-27-managed-host-provider/probe.md
git commit -m "spike(devws): P1 managed-host provider 探针结论 + Phase3 决策"
```

### Task 0b(P2): 容器化 server-launched 路径流式 delta 探针

**Files:**
- Create: `docs/superpowers/spikes/2026-06-27-streaming-delta/probe.md`

- [ ] **Step 1: 在容器化 host(server-launched 或 Task0a 决定的形态)上建会话发 turn,抓 SSE 全事件**

Run(沿用本仓已验证的自测骨架,把 host 换成容器化的):
```bash
cd /Users/yanwen/Documents/github/lite-ai-infra
# 对 codex-native 和 claude-native 各跑一次,dump SSE 所有事件 type,看有无 output_text.delta / external_output_text_delta
uv run python - <<'PY'
import httpx, json, time, threading
c=httpx.Client(base_url="http://localhost:8900", trust_env=False, timeout=120)
# ... 建会话(harness=codex-native)→ launch runner(容器化 host)→ 发 turn → 读 /stream 收集 types
PY
```
Expected: 记录 codex-native / claude-native 各自 SSE 是否含 delta 事件 + 粒度。

- [ ] **Step 2: 记录结论 + 决策(probe.md)**

**决策规则**:
- codex 逐 token delta 到 / claude 段落 delta 到 → Phase 4 前端走增量流(delta 拼接)。
- 仅 codex 到 → 默认 harness=codex-native;claude-native 暂留 items 整段。
- 都不到 → 查 forwarder(`message_deltas.jsonl` 是否产出、forwarder 是否 tail+POST);仍不行则 Phase 4 退回 items 轮询(本计划已有实现),流式标记 vNext。

- [ ] **Step 3: Commit**
```bash
git add docs/superpowers/spikes/2026-06-27-streaming-delta/probe.md
git commit -m "spike(devws): P2 流式 delta 探针结论 + Phase4 决策"
```

> **★ 阶段门**:Task 0a/0b 跑完 → owner 研判 probe.md → 确认 Phase 3/4 走哪条决策分支 → 再继续。

---

## Phase 1 — 全容器化基座(与探针无关,可先做)

### Task 1: 把现有 omnigent 工作树补丁固化进 patch-queue

> 背景:现在 `third_party/omnigent` 工作树有未提交补丁(claude-native 注入会话 MCP〔`build_mcp_config`/`augment_claude_args`/`runner/app.py`〕+ pyproject 加 python-socks)。host 镜像构建走 `scripts/omnigent_build.sh`,它 `git checkout -- .` 清洁源后 **只重放 `deploy/omnigent-patches/*.patch`** → 工作树改动**不会进镜像**。必须先固化成 patch。

**Files:**
- Create: `deploy/omnigent-patches/0001-claude-native-inject-session-mcp.patch`
- Create: `deploy/omnigent-patches/0002-add-python-socks.patch`

- [ ] **Step 1: 从工作树差异生成 patch**
```bash
cd /Users/yanwen/Documents/github/lite-ai-infra/third_party/omnigent
mkdir -p ../../deploy/omnigent-patches
git diff -- omnigent/claude_native_bridge.py omnigent/runner/app.py > ../../deploy/omnigent-patches/0001-claude-native-inject-session-mcp.patch
git diff -- pyproject.toml uv.lock > ../../deploy/omnigent-patches/0002-add-python-socks.patch
```

- [ ] **Step 2: 验证 patch 能干净重放(clean 源 → apply)**
```bash
cd /Users/yanwen/Documents/github/lite-ai-infra
git -C third_party/omnigent stash      # 暂存工作树改动,模拟 clean 源
scripts/omnigent_build.sh dev 2>&1 | tail -5   # 脚本会 checkout + apply patch-queue + build
```
Expected: `apply deploy/omnigent-patches/0001...` / `0002...` 无报错,`built local omnigent-server:dev` + host。

- [ ] **Step 3: 确认 host 镜像带补丁(MCP 注入函数在镜像内)**
```bash
docker run --rm omnigent-host:dev python -c "import omnigent.claude_native_bridge as m, inspect; print('extra_http_servers' in inspect.signature(m.build_mcp_config).parameters)"
```
Expected: `True`(补丁已进镜像)。

- [ ] **Step 4: Commit**
```bash
git add deploy/omnigent-patches/
git commit -m "build(omnigent): 固化 claude-native MCP 注入 + python-socks 补丁进 patch-queue"
```

### Task 2: omnigent server 开 header-auth 多用户 + BFF 发身份头

**Files:**
- Modify: `deploy/dev/omnigent.yml`(`OMNIGENT_AUTH_ENABLED: "1"` + AUTH_PROVIDER header)
- Modify: `configs/local.yaml`(`workspace.send_identity: "1"`)
- Test: `tests/config/test_loader.py`(send_identity 基线)

- [ ] **Step 1: 改 compose 开 header-auth**

`deploy/dev/omnigent.yml` 的 `omnigent.environment`:把 `OMNIGENT_AUTH_ENABLED: "0"` 改为:
```yaml
      OMNIGENT_AUTH_ENABLED: "1"
      OMNIGENT_AUTH_PROVIDER: header
```

- [ ] **Step 2: BFF 切回发身份头**

`configs/local.yaml` 把 `workspace.send_identity: "0"` 改为 `"1"`(多用户:BFF 注入 `X-Forwarded-Email`,omnigent 据此 owner-scope)。

- [ ] **Step 3: 更新基线测试**

`tests/config/test_loader.py` 中 dev 期望 `OMNIGENT_BFF_SEND_IDENTITY` 值改为 `"1"`(若该测试断言具体值)。Run:
```bash
uv run pytest -q tests/config/test_loader.py
```
Expected: PASS。

- [ ] **Step 4: Commit**
```bash
git add deploy/dev/omnigent.yml configs/local.yaml tests/config/test_loader.py
git commit -m "feat(omnigent): server 开 header-auth 多用户 + BFF 发身份头"
```

### Task 3: 容器化 host service(用 omnigent-host 镜像,退役 native)

**Files:**
- Create: `deploy/dev/omnigent-host.yml`
- Modify: `Makefile`(`ws-host-up` 改为起容器化 host;native 版降级为 `ws-host-native` 快验别名)

- [ ] **Step 1: 写容器化 host compose**

`deploy/dev/omnigent-host.yml`(host 连同机 server;NO_PROXY localhost;凭据/host-token 由 Phase 3 注入,本任务先验"容器化 host 能注册"):
```yaml
name: liteai-omnigent-host
services:
  omnigent-host:
    image: ${OMNIGENT_HOST_IMAGE:-omnigent-host}:${OMNIGENT_IMAGE_TAG:-dev}
    network_mode: host           # dev:host 网络,连 127.0.0.1:8900 server
    environment:
      NO_PROXY: localhost,127.0.0.1,::1
      no_proxy: localhost,127.0.0.1,::1
    command: ["omnigent", "host", "http://localhost:8900"]
    restart: unless-stopped
```

- [ ] **Step 2: 起 server + 容器化 host,验注册 online**
```bash
cd /Users/yanwen/Documents/github/lite-ai-infra
scripts/omnigent_build.sh dev
docker compose -f deploy/dev/omnigent.yml up -d
docker compose -f deploy/dev/omnigent-host.yml up -d
sleep 12
curl -s localhost:8900/v1/hosts | uv run python -c "import sys,json;print([h.get('status') for h in json.load(sys.stdin).get('hosts',[])])"
```
Expected: `['online']`(容器化 host 注册成功)。注:header-auth 下若 401,即 P1 探针指出的"host 需 token"——转 Phase 3 的 host-token 注入(此处先用单 host 验通路,多用户 host 在 Phase 3)。

- [ ] **Step 3: Makefile 切换**

`Makefile`:`ws-host-up` 改为 `docker compose -f deploy/dev/omnigent-host.yml up -d`;原 native 那条改名 `ws-host-native`(注释:仅"改 omnigent 源码后本地快验"用,非常态)。

- [ ] **Step 4: Commit**
```bash
git add deploy/dev/omnigent-host.yml Makefile
git commit -m "feat(omnigent): 容器化 host(omnigent-host 镜像),native 降级为快验别名"
```

---

## Phase 2 — per-user 订阅凭据流(与探针无关,可先做)

### Task 4: 凭据加密存储(Fernet credential vault)

**Files:**
- Create: `services/credential_vault/__init__.py`
- Create: `services/credential_vault/vault.py`
- Test: `tests/credential_vault/test_vault.py`

- [ ] **Step 1: 写失败测试**

`tests/credential_vault/test_vault.py`:
```python
from services.credential_vault.vault import CredentialVault

def test_put_get_roundtrip_encrypts_at_rest(tmp_path):
    v = CredentialVault(key="izUz8HYmu8l-FHzVXypDBEyGRuf33opI-Jf3xGaLgaw=", store_dir=tmp_path)
    v.put(user_id="u-alice", provider="claude", secret="oauth-tok-123")
    # 落盘必须是密文,不含明文
    blob = (tmp_path / "u-alice.json").read_bytes()
    assert b"oauth-tok-123" not in blob
    assert v.get(user_id="u-alice", provider="claude") == "oauth-tok-123"

def test_status_and_delete(tmp_path):
    v = CredentialVault(key="izUz8HYmu8l-FHzVXypDBEyGRuf33opI-Jf3xGaLgaw=", store_dir=tmp_path)
    v.put(user_id="u-bob", provider="codex", secret="{\"OPENAI_API_KEY\":\"x\"}")
    assert v.status(user_id="u-bob") == {"claude": False, "codex": True}
    v.delete(user_id="u-bob", provider="codex")
    assert v.status(user_id="u-bob") == {"claude": False, "codex": False}
```

- [ ] **Step 2: 跑测试确认失败**
```bash
uv run pytest -q tests/credential_vault/test_vault.py
```
Expected: FAIL(模块不存在)。

- [ ] **Step 3: 实现 vault**

`services/credential_vault/vault.py`:
```python
from __future__ import annotations
import json
from pathlib import Path
from cryptography.fernet import Fernet

_PROVIDERS = ("claude", "codex")

class CredentialVault:
    """per-user 订阅凭据加密存储。明文绝不落盘(§5.2);仅 launch host 时解密注入。"""
    def __init__(self, key: str, store_dir: Path):
        self._f = Fernet(key.encode() if isinstance(key, str) else key)
        self._dir = Path(store_dir); self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, user_id: str) -> Path:
        return self._dir / f"{user_id}.json"

    def _read(self, user_id: str) -> dict:
        p = self._path(user_id)
        return json.loads(p.read_text()) if p.exists() else {}

    def put(self, *, user_id: str, provider: str, secret: str) -> None:
        assert provider in _PROVIDERS
        data = self._read(user_id)
        data[provider] = self._f.encrypt(secret.encode()).decode()
        self._path(user_id).write_text(json.dumps(data))

    def get(self, *, user_id: str, provider: str) -> str | None:
        token = self._read(user_id).get(provider)
        return self._f.decrypt(token.encode()).decode() if token else None

    def status(self, *, user_id: str) -> dict:
        data = self._read(user_id)
        return {p: (p in data) for p in _PROVIDERS}

    def delete(self, *, user_id: str, provider: str) -> None:
        data = self._read(user_id)
        data.pop(provider, None)
        self._path(user_id).write_text(json.dumps(data))
```
`services/credential_vault/__init__.py`:`from services.credential_vault.vault import CredentialVault`

- [ ] **Step 4: 跑测试确认通过**
```bash
uv run pytest -q tests/credential_vault/test_vault.py
```
Expected: PASS。

- [ ] **Step 5: Commit**
```bash
git add services/credential_vault/ tests/credential_vault/
git commit -m "feat(vault): per-user 订阅凭据 Fernet 加密存储"
```

### Task 5: onboarding API(提交/查状态/删)+ 设置页

**Files:**
- Create: `services/gateway/bff/credentials_routes.py`
- Modify: `services/gateway/bff/middleware.py`(挂载 router + 注入 vault)
- Create: `frontend/src/pages/devws/ModelCredentials.tsx`
- Test: `tests/gateway/bff/test_credentials_routes.py`

- [ ] **Step 1: 写失败测试(路由按会话身份隔离)**

`tests/gateway/bff/test_credentials_routes.py`:
```python
# 用 TestClient + 伪 BFF 会话(沿用 test_workspace_routes 的会话夹具),断言:
# - GET /v1/me/model-credentials → {"claude": false, "codex": false}(未连接)
# - POST /v1/me/model-credentials {provider:"claude", secret:"tok"} → 200;再 GET → claude: true
# - 未认证 → 401;secret 不在任何响应里回显
```

- [ ] **Step 2: 跑测试确认失败**
```bash
uv run pytest -q tests/gateway/bff/test_credentials_routes.py
```
Expected: FAIL。

- [ ] **Step 3: 实现 router**

`services/gateway/bff/credentials_routes.py`:`make_credentials_router(*, claims, vault)`,路由:
- `GET /v1/me/model-credentials` → `vault.status(user_id=ctx.user)`
- `POST /v1/me/model-credentials` body `{provider, secret}` → `vault.put(...)` → `{"ok": true}`(**不回显 secret**)
- `DELETE /v1/me/model-credentials/{provider}` → `vault.delete(...)`
身份取自 `_resolve(request, claims)`(复用 workspace_routes 的会话解析),CSRF 双提交(沿用现有 `mut`)。

`middleware.py`:`install_bff` 里建 `CredentialVault(key=WS_TOKEN_KEY 或独立 CRED_KEY, store_dir=...)` 并 `mount make_credentials_router(...)`.

- [ ] **Step 4: 跑测试确认通过**
```bash
uv run pytest -q tests/gateway/bff/test_credentials_routes.py
```
Expected: PASS。

- [ ] **Step 5: 前端设置页(第一个消费者,低保真)**

`frontend/src/pages/devws/ModelCredentials.tsx`:展示 claude/codex 连接状态;每个 provider 一个输入框(粘贴 `claude setup-token` 输出 / codex auth.json)+ 「连接」按钮 → `POST /v1/me/model-credentials`;「断开」→ DELETE。复用 `api/devws.ts` 的 `mut`/csrf。加 `frontend/src/pages/devws/ModelCredentials.test.tsx`(渲染 + 提交调用断言)。

- [ ] **Step 6: 跑前端测试 + lint**
```bash
cd frontend && npx vitest run src/pages/devws/ModelCredentials.test.tsx && npm run lint
```
Expected: PASS + lint 干净。

- [ ] **Step 7: Commit**
```bash
git add services/gateway/bff/credentials_routes.py services/gateway/bff/middleware.py tests/gateway/bff/test_credentials_routes.py frontend/src/pages/devws/ModelCredentials.tsx frontend/src/pages/devws/ModelCredentials.test.tsx
git commit -m "feat(bff): 订阅凭据 onboarding API + 连接订阅设置页"
```

---

## Phase 3 — per-user host 编排 + 凭据注入(★ GATE on P1;默认按 0a 决策 (c))

> 本阶段按 **Task 0a 的决策结论**实现。下方默认按 (c)「我们侧编排 `docker run` per-user host + host token 注册」写;若 0a 命中 (a)/(b),Step 实现替换为 omnigent 原生 managed-host launch(更简,去掉 docker run 部分,保留凭据注入与 ensure 逻辑)。

### Task 6: per-user host 编排器(ensure host online + 注入凭据/host-token)

**Files:**
- Create: `services/gateway/bff/managed_host.py`
- Test: `tests/gateway/bff/test_managed_host.py`

- [ ] **Step 1: 写失败测试(ensure 幂等 + 凭据注入构造)**

`tests/gateway/bff/test_managed_host.py`:
```python
from services.gateway.bff.managed_host import build_host_launch_env, host_name_for

def test_host_name_is_per_user_opaque():
    assert host_name_for("u-alice") == host_name_for("u-alice")        # 稳定
    assert host_name_for("u-alice") != host_name_for("u-bob")          # 隔离

def test_launch_env_injects_user_subscription_and_host_token():
    env = build_host_launch_env(claude_token="ctok", codex_auth_json='{"OPENAI_API_KEY":"k"}', host_token="htok")
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "ctok"
    assert env["OMNIGENT_HOST_TOKEN"] == "htok"
    assert env["NO_PROXY"].startswith("localhost")
    # codex auth.json 走文件,不进 env 明文
    assert "OPENAI_API_KEY" not in str(env)
```

- [ ] **Step 2: 跑测试确认失败 → 实现 → 跑通**

实现 `managed_host.py`:`host_name_for(user_id)`(稳定不透明名)、`build_host_launch_env(...)`、`ensure_host_online(*, user_id, vault, omni, runner)`(查 server 有无该 user 在线 host;无则:server 签发 host-token → `docker run --network host -e ... omnigent-host:dev`〔(c) 路径〕或调 omnigent managed-launch〔(a)/(b)〕;codex auth.json 经临时挂载注入;轮询直到 online 或超时报错)。codex 凭据写文件注入(不进 env)。
Run: `uv run pytest -q tests/gateway/bff/test_managed_host.py` → PASS。

- [ ] **Step 3: Commit**
```bash
git add services/gateway/bff/managed_host.py tests/gateway/bff/test_managed_host.py
git commit -m "feat(bff): per-user host 编排(ensure online + 订阅凭据/host-token 注入)"
```

### Task 7: 建会话先确保该用户 host,再 launch_runner

**Files:**
- Modify: `services/gateway/bff/workspace.py`(`create_workspace_session`)
- Test: `tests/dev_workspace/test_bff_workspace.py`

- [ ] **Step 1: 改测试**

`test_bff_workspace.py` 的 `create_workspace_session` 用例:断言建会话时调用 `ensure_host_online(user_id=sub, ...)`,且 `launch_runner` 用的是返回的该用户 `host_id`(不再 `first_online_host()` 取任意 host)。

- [ ] **Step 2: 跑测试确认失败 → 改 `create_workspace_session`**

把 `host_id = omni.first_online_host()` 改为 `host_id = ensure_host_online(user_id=sub, vault=..., omni=..., runner=...)`;其余(铸令牌/register_mcp/launch_runner/hydrate)不变。workspace 用该 host 内 per-session 目录。
Run: `uv run pytest -q tests/dev_workspace/` → PASS。

- [ ] **Step 3: Commit**
```bash
git add services/gateway/bff/workspace.py tests/dev_workspace/test_bff_workspace.py
git commit -m "feat(bff): 建会话确保 per-user host 在线后再 launch_runner"
```

---

## Phase 4 — 前端增量流式(★ GATE on P2;默认按 0b 决策)

### Task 8: useSessionStream 增量流式(delta)+ items 兜底

**Files:**
- Modify: `frontend/src/pages/devws/useSessionStream.ts`
- Test: `frontend/src/pages/devws/useSessionStream.test.ts`

> 按 **Task 0b 决策**:delta 到 → 本任务实现;都不到 → 跳过本任务,保留现有 items 轮询(流式标 vNext),并在计划勾注说明。

- [ ] **Step 1: 加 applyStreamEvent 的 delta 测试(已有 output_text.delta;补 external_output_text_delta)**

`useSessionStream.test.ts` 增:`external_output_text_delta`(claude-native 段落级)累积进同一 assistant 气泡的用例。

- [ ] **Step 2: 跑测试确认失败 → 改 applyStreamEvent + hook**

`applyStreamEvent`:把 `t === 'response.output_text.delta'` 的分支扩为同时认 `external_output_text_delta`(两者都取 `ev.delta` 累积)。`useSessionStream`:SSE 事件**先走 applyStreamEvent 增量拼接**(流式);`response.completed` 时 refetch `/items` 对账(兜底纠正,去重)。保留 ASK 卡片分支。
Run: `cd frontend && npx vitest run src/pages/devws/useSessionStream.test.ts` → PASS。

- [ ] **Step 3: lint + build**
```bash
cd frontend && npm run lint && npm run build
```
Expected: 干净 + built。

- [ ] **Step 4: Commit**
```bash
git add frontend/src/pages/devws/useSessionStream.ts frontend/src/pages/devws/useSessionStream.test.ts
git commit -m "feat(devws): 增量流式渲染(delta)+ items 兜底对账"
```

---

## Phase 5 — 全栈编排 + 验收 runbook

### Task 9: ws-up 全容器化编排 + 手动验收 runbook

**Files:**
- Modify: `Makefile`(`ws-up` 用容器化 host)
- Modify: `docs/superpowers/plans/2026-06-26-dev-workspace/RUNBOOK.md`(加全容器化 + 双用户段)

- [ ] **Step 1: `ws-up` 编排**

`Makefile` `ws-up`:`omnigent-image`(build server+host)→ `omnigent-up`(server)→ `up`(我们服务)→ `omnigent-host`(容器化 host〔dev 单 host 或 Phase3 的 per-user 编排〕)→ `ws-fe-up`。去掉 native host 依赖。

- [ ] **Step 2: 全量门禁**
```bash
cd /Users/yanwen/Documents/github/lite-ai-infra
uv run pytest -q && uv run lint-imports && bash scripts/ci_guards.sh
cd frontend && npm run lint && npx vitest run && npm run build
```
Expected: 全绿。

- [ ] **Step 3: 手动验收 runbook(写进 RUNBOOK.md 并实跑)**

可证伪验收(双用户):
1. `make ws-up`(全容器化,无 native host 进程:`pgrep -f "omnigent host" 在主机应为空,host 在容器内`)。
2. 浏览器 alice 登录 → 设置页连接 alice 的 claude 订阅 → 发消息:**回复增量出现**(非整段;codex 逐字 / claude 段落)。
3. 另一浏览器/隐身 bob 登录 → 连接 bob 自己的订阅 → 各自会话;**alice 看不到 bob 的会话/数据**(承重墙 can() + per-user host)。
4. parity 自检:`docker images | grep omnigent`(server+host 同 tag);dev 跑的就是镜像(非主机 `uv run`)。
5. 负向:伪造 `X-Forwarded-Email` 经前端到不了 omnigent(BFF 剥离);无凭据起会话 → 明确报「未连接订阅」。

- [ ] **Step 4: Commit**
```bash
git add Makefile docs/superpowers/plans/2026-06-26-dev-workspace/RUNBOOK.md
git commit -m "feat(devws): ws-up 全容器化编排 + 双用户验收 runbook"
```

---

## DoD(完成定义)

- [ ] Phase 0 两探针跑完 + probe.md 成文 + owner 研判确认 Phase 3/4 分支
- [ ] omnigent server+host **全容器化同镜像**;主机无 native `omnigent host` 进程(parity §5.3)
- [ ] header-auth 多用户;双用户互不可见(承重墙 can() + per-user host)
- [ ] per-user 订阅凭据加密存储(§5.2,明文不落盘/日志/响应)+ 注入各自 host
- [ ] 回复**增量流式**(按 P2 决策;退化则 items 轮询 + 流式标 vNext)
- [ ] sandbox=none(显式推迟,RUNBOOK 注明)
- [ ] `make test` + `make lint` + 前端 lint/test/build 全绿
- [ ] 手动验收 runbook 双用户 live 通过
