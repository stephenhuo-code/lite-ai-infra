# S1 Plan 6:BFF 后端(gateway OIDC 会话 + `GET /v1/data/jobs`,出口⑤ GUI 前置)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal(ADR-019):** 把 gateway 由薄反代壳升级为 **BFF**——服务端 OIDC 登录/会话/登出、会话→下游 bearer 注入、CSRF;并补 `GET /v1/data/jobs`(GUI 作业页需要)。本计划**纯后端**,curl 跑通 OIDC 全链路即可独立验收(前端 = Plan 7)。

**Architecture(ADR-019 + product-architect 复审):**
- **会话逻辑独立模块 `services/gateway/bff/`**(与反代物理隔离,为 v2 拆分留缝;不长进 `build_gateway`)。
- **会话 = 无状态 Fernet 加密 cookie**(v1 无 PG;规避 Redis 的独立取舍,置会话存储 seam 后,v2 可换)。装 `{access, refresh, exp}`;HttpOnly/SameSite=Lax。
- **吊销窗口(登记风险)**:无中心吊销 → **access token TTL ≤ 5min + refresh 轮换**,把踢人/改组的隔离风险窗口压到 ≤5min。
- **OIDC**:Authorization Code + **PKCE**;专用机密客户端 `lite-ai-web`(窄回调、**无 ROPC**,满足复审 C-4);`gateway` 客户端保留 ROPC 给测试/ops。
- **会话→bearer**:中间件解会话 cookie → access 过期则刷新 → 注入 `Authorization: Bearer` 给下游反代(**取代**原"透传客户端 bearer")。
- **CSRF**:SameSite=Lax + 双提交 token(可读 cookie 副本 + 变更请求带 `X-CSRF-Token`);副作用端点严格非 GET。
- **`GET /v1/data/jobs`**:契约先行 + **必经 `can()` 按企业/组过滤**(`JobStore.list_jobs`)+ 分页;作业量上千需索引,显式登记 vN+。

**Tech Stack:** FastAPI、httpx、`cryptography` Fernet(已随 pyjwt[crypto] 在)、Keycloak(realm 加客户端)、既有 `libs/identity`(JWKS 验签复用)、pytest 两层。

**端口/env:** gateway 8090;新 env `BFF_SESSION_KEY`(Fernet key)、`OIDC_CLIENT_ID=lite-ai-web`、`OIDC_CLIENT_SECRET`、`OIDC_ISSUER`(默认 `http://localhost:8080/realms/lite-ai`)、`BFF_REDIRECT_URI`(默认 `http://localhost:8090/auth/callback`)。

---

### Task 1:探查(真 Keycloak)—— 钉死 refresh/cookie 事实(宪法 §3.4 探查优先)

> 复审 I-2:无状态 + refresh 轮换有并发死结;必须先实测,**禁止把猜测写进实现**。

**Files:** 创建:`spikes/bff_oidc/probe.md`(事实记录)、`spikes/bff_oidc/probe.sh`

- [ ] **步骤 1:真 Keycloak 跑通 Authorization Code + PKCE 流**(`make dev-up` 后,手动浏览器或脚本):拿 code → 换 token;记录 access/refresh/id token 的**实际大小**与 access token **TTL**(realm 默认 `accessTokenLifespan`)。**(M-2)** 若 TTL **> 5min 且 ops 不可调** → 这是偏离 ADR-019(吊销窗口 ≤5min 缓解失效)→ **登记为风险偏离并 escalate owner**(不得默默接受);确认可调到 ≤5min 则记目标值。
- [ ] **步骤 2:实测 refresh rotation 行为** —— 用同一 refresh token **连续刷新两次**,看第二次是否被拒(Keycloak `Revoke Refresh Token`/rotation 是否开)。结论二选一定死:
  - rotation **开** → **single-flight(per-`sub` 共享结果,非仅串行)**:单副本进程内按 `sub` 加 `asyncio.Lock`,**lock 内 double-check** —— 进锁后先看是否已有并发请求刚刷出的新 token(缓存),有则**复用**、不重复刷(否则后到请求拿失效旧 refresh 去刷→随机登出,这才是 I-2 真死结);
  - rotation **关** → 无需锁,直接刷新。
- [ ] **步骤 3:实测 cookie 体积** —— `{access+refresh+exp}` Fernet 加密后字节数;确认 < 4KB(单 cookie 上限)。多组用户(groups full-path claim)取最坏样本。**> 4KB 则方案降级**(只存 refresh + 用 refresh 换 access;或拆 cookie)——记进 probe.md。
- [ ] **步骤 4:产出 `spikes/bff_oidc/probe.md`**(token 大小/TTL/rotation 结论/cookie 体积/refresh 策略决定)+ 提交 `spike(bff): real Keycloak OIDC code+PKCE / refresh rotation / cookie size facts`

---

### Task 2:realm 加固 + 专用 BFF 客户端(复审 C-4,DoD 硬门)

**Files:** 修改:`deploy/dev/keycloak/realm-lite-ai.json`

- [ ] **步骤 1:加专用机密客户端 `lite-ai-web`**(授权码流、窄回调、**无 ROPC**)

```json
{ "clientId": "lite-ai-web", "publicClient": false, "secret": "dev-web-secret",
  "standardFlowEnabled": true, "directAccessGrantsEnabled": false,
  "redirectUris": ["http://localhost:8090/auth/callback"],
  "webOrigins": ["http://localhost:8090"] }
```
> `gateway` 客户端**保留**(其 ROPC 给集成测试/runbook 取 token;BFF 不用它)。BFF 用的 `lite-ai-web` 无 ROPC、回调精确 —— 满足复审 C-4 "BFF 客户端不留开放重定向/ROPC"。

- [ ] **步骤 2:DoD 硬门登记**(写进本 plan 验收 + README):**prod realm 另发**——`lite-ai-web` secret 走 secret 管理(非 `dev-web-secret`)、`webOrigins`/`redirectUris` 用 prod 域名、`gateway` 客户端 prod 关 ROPC。dev 用上面值。
- [ ] **步骤 3:`make dev-up` 重导 realm,确认 `lite-ai-web` 生效**(authorize 端点对它返回登录页);**步骤 4:提交** `feat(bff): dedicated lite-ai-web OIDC client (code-flow, no ROPC, narrow redirect)`

---

### Task 3:`gateway/bff/session.py` —— Fernet 加密会话 cookie(TDD,纯逻辑)

**Files:** 创建:`services/gateway/bff/__init__.py`、`services/gateway/bff/session.py`、`tests/gateway/bff/__init__.py`、`tests/gateway/bff/test_session.py`

- [ ] **步骤 1:写失败测试**(编/解码 roundtrip;坏/篡改 cookie → None;过期判定)

```python
# tests/gateway/bff/test_session.py
from cryptography.fernet import Fernet
from services.gateway.bff.session import SessionCodec, SessionData

def _codec(): return SessionCodec(Fernet.generate_key())

def test_roundtrip():
    c = _codec()
    s = SessionData(access_token="a", refresh_token="r", expires_at=1900000000)
    got = c.decode(c.encode(s))
    assert got.access_token == "a" and got.refresh_token == "r" and got.expires_at == 1900000000

def test_tampered_cookie_returns_none():
    assert _codec().decode("not-a-valid-token") is None

def test_is_expired():
    assert SessionData("a","r",0).is_expired(now=100) is True
    assert SessionData("a","r",1000).is_expired(now=100) is False
```

- [ ] **步骤 2:跑红**;**步骤 3:实现**(Fernet 对称加密 JSON;key 从 env;decode 容错返 None)

```python
# services/gateway/bff/session.py
from __future__ import annotations
import json
from dataclasses import dataclass, asdict
from cryptography.fernet import Fernet, InvalidToken

@dataclass
class SessionData:
    access_token: str
    refresh_token: str | None
    expires_at: int                      # epoch 秒(access token 过期点)
    csrf: str = ""                        # 双提交 CSRF token(登录时一次生成,Task 6;与明文 csrf_token cookie 同值)
    def is_expired(self, now: int, skew: int = 30) -> bool:
        return now >= self.expires_at - skew

class SessionCodec:
    def __init__(self, key: bytes): self._f = Fernet(key)
    def encode(self, s: SessionData) -> str:
        return self._f.encrypt(json.dumps(asdict(s)).encode()).decode()
    def decode(self, token: str) -> SessionData | None:
        try:
            return SessionData(**json.loads(self._f.decrypt(token.encode())))
        except (InvalidToken, ValueError, TypeError):
            return None
```

- [ ] **步骤 4:跑绿**;**步骤 5:提交** `feat(bff): Fernet-encrypted stateless session codec`

---

### Task 4:OIDC 登录流 `/auth/login` · `/auth/callback` · `/auth/logout`(TDD)

> 复审 I-3:`/auth/callback` 必须校验 `state` + PKCE `code_verifier`。token 端点交换用注入 seam 测。

**Files:** 创建:`services/gateway/bff/oidc.py`、`services/gateway/bff/routes.py`、`tests/gateway/bff/test_oidc_flow.py`

- [ ] **步骤 1:写失败测试**(login→302 到 Keycloak authorize 且带 state+code_challenge,并下发临时 state cookie;callback state 不匹配→400;匹配→换 token(fake)→下发会话 cookie→302 回 `/`;logout→清 cookie)

```python
# tests/gateway/bff/test_oidc_flow.py
import httpx
from fastapi.testclient import TestClient
from services.gateway.bff.routes import build_auth_router_app   # 测试用最小 app 挂 auth 路由

def _app(monkeypatch):
    monkeypatch.setenv("BFF_SESSION_KEY", __import__("cryptography.fernet",fromlist=["Fernet"]).Fernet.generate_key().decode())
    monkeypatch.setenv("OIDC_CLIENT_ID","lite-ai-web"); monkeypatch.setenv("OIDC_CLIENT_SECRET","s")
    monkeypatch.setenv("OIDC_ISSUER","http://kc/realms/x"); monkeypatch.setenv("BFF_REDIRECT_URI","http://gw/auth/callback")
    # token 端点交换 seam:返回假 token
    def fake_exchange(code, verifier): return {"access_token":"at","refresh_token":"rt","expires_in":300}
    return build_auth_router_app(exchange_code=fake_exchange)

def test_login_redirects_to_authorize_with_pkce(monkeypatch):
    r = TestClient(_app(monkeypatch)).get("/auth/login", follow_redirects=False)
    assert r.status_code == 302
    loc = r.headers["location"]
    assert "response_type=code" in loc and "code_challenge=" in loc and "state=" in loc
    assert "oidc_state" in r.cookies      # 临时 state/verifier cookie 已下发

def test_callback_bad_state_400(monkeypatch):
    c = TestClient(_app(monkeypatch))
    assert c.get("/auth/callback?code=x&state=mismatch", follow_redirects=False).status_code == 400

def test_logout_clears_cookie(monkeypatch):
    r = TestClient(_app(monkeypatch)).post("/auth/logout", follow_redirects=False)
    assert 'session=' in r.headers.get("set-cookie","") and "Max-Age=0" in r.headers.get("set-cookie","")
```

- [ ] **步骤 2:跑红**;**步骤 3:实现** `oidc.py`(authorize URL 构造 + PKCE S256 + 真 token 交换 `exchange_code`,默认打 Keycloak token 端点用 `lite-ai-web`+secret;可注入 seam)、`routes.py`(三路由:login 生成 state/verifier 存临时签名 cookie + 302;callback 校验 state→exchange→**生成 csrf**→建 `SessionData(exp=now+expires_in, csrf=…)`→set 加密会话 cookie + **下发非 HttpOnly `csrf_token` 同值明文 cookie**(I-3 唯一写入点)+ 清临时 cookie + 302 `/`;logout 清会话 + csrf cookie)。
- [ ] **步骤 4:跑绿**;**步骤 5:提交** `feat(bff): OIDC code+PKCE login/callback/logout`

---

### Task 5:会话中间件 + 会话→bearer 注入 + 过期刷新 + `/auth/me`(TDD)

> 改造反代:不再透传客户端 bearer,改为**从会话注入**。刷新按 Task 1 结论(single-flight 或直刷)。

**Files:** 创建:`services/gateway/bff/middleware.py`;修改:`services/gateway/app.py`(build_gateway 接 BFF)、`services/_scaffold/proxy.py`(bearer 来源改 request.state)、`tests/gateway/bff/test_session_mw.py`

- [ ] **步骤 1:写失败测试**(有效会话→请求注入 Bearer 透传下游 stub;无会话→受保护路由 401;access 过期 + 有 refresh→触发刷新(fake)并更新 cookie;`/auth/me` 返回 user+csrf)

```python
# tests/gateway/bff/test_session_mw.py  (要点)
# - 构会话 cookie(SessionCodec 编码 SessionData),带 cookie 打 /v1/... → 下游 stub 收到 Authorization: Bearer <access>
# - 无 cookie 打 /v1/... → 401
# - 【C-1 红线负向】伪造 Authorization: Bearer forged + 无会话 cookie 打 /v1/... → 401(绝不透传 forged 给下游)
# - 【C-1 红线负向】有会话 cookie + 同时带客户端 Authorization: Bearer forged → 下游收到的是会话 access(非 forged)
# - 【C-2】access 过期 + refresh fake 刷新 → 下游收到新 access **且当前响应带 Set-Cookie**(解码出新 access)
# - 【I-4】refresh 端点返回错误 → 401 + 响应 Set-Cookie session Max-Age=0(清 cookie)
# - GET /auth/me → {user, is_platform_admin, csrf}(user/memberships 解自会话内 access token,不存 id_token)
```

- [ ] **步骤 2:跑红**;**步骤 3:实现**:
  - **(C-1,proxy 命门)** `_scaffold/proxy.py`:从 `_FWD_HEADERS` **删除 `"authorization"`**;bearer **只**由 BFF 从 `request.state.bearer` 写入 fwd_headers,`request.state.bearer` 缺失则**不转发任何 authorization**(让下游 401),**绝不回退客户端原值**。gateway 是 mount_proxy 唯一使用者,安全。
  - **(C-2,中间件两阶段)** `middleware.py` `@app.middleware("http")`,严格分两段:**call_next 前**——解会话 cookie → 无/坏 → 受保护路由(`/v1/*`、`/auth/me`)返 401;有效 → 过期且有 refresh 则刷新 → 设 `request.state.bearer` + 把待下发新会话挂 `request.state.new_session`;**call_next 后**——若 `request.state.new_session` 存在则 `response.set_cookie(...)` 下发到**当前响应**。Task 8 接线须显式定中间件注册顺序(会话中间件包在 proxy 路由外层、request-id 内层)。
  - **(I-1,单飞共享)** 刷新按 Task 1 结论:rotation 开 → per-`sub` `asyncio.Lock` + **lock 内 double-check**(已被并发请求刷过则**复用其结果**,不重复刷,避免 rotation 让旧 refresh 失效→随机登出);rotation 关 → 直刷。
  - **(I-4,刷新失败降级)** 刷新调用失败(refresh 也过期/被吊销)→ **清会话 cookie(Max-Age=0)+ 受保护路由返 401**(前端据此跳登录),不得抛 500。
  - **(M-3)** `/auth/me`:解**会话内 access token** 的 claims 返回 `{user, is_platform_admin, csrf}`(access 已在会话,无需存 id_token、无需多跳 identity)。
- [ ] **步骤 4:跑绿**;**步骤 5:提交** `feat(bff): session middleware + bearer injection + refresh + /auth/me`

---

### Task 6:CSRF 双提交(TDD)

**Files:** 修改:`services/gateway/bff/middleware.py`;创建:`tests/gateway/bff/test_csrf.py`

- [ ] **步骤 1:写失败测试**(POST/PUT/DELETE/PATCH 缺/错 `X-CSRF-Token`→403;匹配 `SessionData.csrf`→放行;GET 豁免;**`/auth/logout`(POST)需 CSRF**(缺→403);**`/auth/login`·`/auth/callback` 豁免**)
- [ ] **步骤 2:跑红**;**步骤 3:实现**:
  - **(I-3)csrf 在登录回调一次生成**(Task 4 callback 建会话时):写进 `SessionData.csrf`(加密会话内)**同时**下发**非 HttpOnly** `csrf_token` 明文 cookie(**同值**,双提交一致性靠这一处唯一写入)。
  - **(C-3)CSRF 豁免清单定死**:豁免 `/auth/login`、`/auth/callback`(均 GET,本豁免);**`/auth/logout`(POST)不豁免、需 `X-CSRF-Token`**(防 CSRF 强制登出);所有 GET 豁免(副作用端点严格非 GET 方成立)。
  - 变更方法校验 `X-CSRF-Token` header == 会话内 `csrf`(非仅 == 明文 cookie,防 cookie 注入)。
- [ ] **步骤 4:跑绿**;**步骤 5:提交** `feat(bff): double-submit CSRF on mutating requests`

---

### Task 7:`GET /v1/data/jobs`(契约 + JobStore.list_jobs + can() 过滤 + 分页,TDD)

> 复审 I-1:**必经 can() 按企业/组过滤**,不裸暴露 `_all_status()` 跨企业。

**Files:** 修改:`contracts/openapi/data-pipeline.yaml`(加 `GET /v1/data/jobs` + `JobList`)、`Makefile gen`(契约已在 gen 列,重生成模型)、`services/data_pipeline_service/jobs.py`(加 `list_jobs`)、`services/data_pipeline_service/app.py`(加 handler)、`tests/services/data_pipeline/test_list_jobs.py`

- [ ] **步骤 1:契约加端点**

```yaml
  /v1/data/jobs:
    get:
      parameters:
        - {name: status, in: query, required: false, schema: {type: string, enum: [queued,running,succeeded,failed]}}
        - {name: limit, in: query, required: false, schema: {type: integer, default: 50, maximum: 200}}
        - {name: offset, in: query, required: false, schema: {type: integer, default: 0}}
      responses:
        '200': {description: jobs, content: {application/json: {schema: {$ref: '#/components/schemas/JobList'}}}}
        '401': {description: unauthenticated}
# components.schemas 加:
    JobList:
      type: object
      required: [jobs, total]
      properties:
        jobs: {type: array, items: {$ref: '#/components/schemas/Job'}}
        total: {type: integer}
```

- [ ] **步骤 2:`make gen` 重生成模型(freshness 绿)**
- [ ] **步骤 3:写失败测试**(本组作业可见、跨组/跨企业不可见、status 过滤、分页 limit/offset、total 为过滤后总数)

```python
# tests/services/data_pipeline/test_list_jobs.py(要点)
# seam 开;u-alice@g-0001 提交 2 job、构造一条 e-0001/g-0002 的 job 文件
# GET /v1/data/jobs → 只见 g-0001 的(can() 过滤);?status=succeeded 只见成功;?limit=1&offset=1 分页
# total = 过滤后总数(非全量)
# 【I-2 fail-closed】构造一条 spec.json 缺失的损坏 job(read 返回 enterprise_id=None)→ 必被排除,不漏给任何企业
```

- [ ] **步骤 4:跑红**;**步骤 5:实现**:
  - **(I-2)** `JobStore.list_jobs() -> list[dict]`:遍历目录 → 对每个 `read(job_id)` **投影**(含 `enterprise_id`/`group_id` —— 这两字段在 **spec.json**,`_all_status()` 只读 status.json 拿不到,**不能用 `_all_status()` 否则无法 can() 过滤→隔离失效**);按 created_at 倒序;**纯取数,不做授权**。
  - `app.py` handler:`ent=enterprise_of(ctx)`;对每条 **fail-closed** 跳过 `enterprise_id` 为 None/≠ent 的(对照 metadata `_owner_group` fail-closed),再 `can(ctx,"data.read",Resource(kind="job",ent,group_id=job["group_id"])).allow` 才纳入;status 过滤 + `offset:offset+limit` 切片;`total`=过滤后条数。**契约注释登记:扫目录 O(n),作业量上千需索引(vN+)。**
- [ ] **步骤 6:跑绿 + `make gen` 无 diff + lint-imports**;**步骤 7:提交** `feat(data-pipeline): GET /v1/data/jobs (can()-filtered, paginated)`

---

### Task 8:接线 + 集成(真 Keycloak curl 全链路)+ 验收 + 合并

**Files:** 修改:`services/gateway/main.py`(挂 BFF:auth 路由 + 会话/CSRF 中间件 + env)、`scripts/dev_services.sh`(gateway env 加 `BFF_*`/`OIDC_*`)、`README.md`;创建:`tests/integration/test_bff_oidc.py`

- [ ] **步骤 1:接线** `main.py`:`build_gateway(routes=…)` 之上挂 BFF(auth router + 中间件)。**(C-2)显式中间件顺序**:`@app.middleware` 后注册先执行(LIFO)——保证会话中间件**包在 proxy 路由外层**(call_next 前设好 `request.state.bearer`)、在 request-id 中间件内层;`main.py` 注释写死次序并加守护断言/测试。`dev_services.sh` gateway 分支加 `BFF_SESSION_KEY`(dev 固定值)、`OIDC_CLIENT_ID=lite-ai-web`、`OIDC_CLIENT_SECRET=dev-web-secret`、`OIDC_ISSUER`、`BFF_REDIRECT_URI`。
- [ ] **步骤 2:集成测试**(标 `integration`;真 Keycloak code 流难全自动 → 用真 Keycloak **直接 authorize+登录拿 code** 的脚本化 session,或退而验:会话 cookie 手工构造(真 token 经 `gateway` ROPC 取)→ 带 cookie 打 `/v1/data/jobs` 200 + 注入 bearer 下游通;无 cookie→401;CSRF 缺头→403)。完整浏览器 code 流由人工 runbook 验。
- [ ] **步骤 3:`make up` 后** `uv run pytest -q -m integration` + `uv run pytest -q && uv run lint-imports && bash scripts/ci_guards.sh` 全绿。
- [ ] **步骤 4:手动验收**(文末 runbook:真浏览器 OIDC 登录全链路)。贴输出。
- [ ] **步骤 5:requesting-code-review 子代理隔离评审 → 修 Critical/Important(宪法 §3.4/ADR-017)。**
- [ ] **步骤 6:回写状态**(本 plan checkbox + spec §5.3/§9.3 Plan 6 标 ✅ + 出口⑤ 进度"BFF 后端就绪,待 Plan 7 前端")+ 提交 + 合并。

---

## 验收对照(ADR-019 + 复审)

| 要素 | 任务 |
|---|---|
| refresh/cookie 事实钉死(I-2)| Task 1 探查 |
| realm 加固 / 无 ROPC BFF 客户端(C-4)| Task 2 |
| 无状态加密 cookie 会话(C-2)| Task 3 |
| OIDC code+PKCE + state 校验(I-3)| Task 4 |
| 会话→bearer 注入(取代透传)| Task 5(+ proxy 改造)|
| access≤5min + 过期刷新(C-2)| Task 1 定策略 + Task 5 实现 |
| CSRF 双提交(I-3)| Task 6 |
| `GET /v1/data/jobs` can()+分页(I-1)| Task 7 |
| 会话逻辑独立模块 `gateway/bff/`(C-3)| Task 3–6 |
| 独立验收(curl 全链路,M-1)| Task 8 runbook |
| **🔴 红线:客户端伪造 bearer 不绕过会话(C-1)** | Task 5 proxy 删 authorization 转发 + 负向测试(伪造 bearer+无会话→401)|
| 中间件两阶段 + 刷新随当前响应下发(C-2)| Task 5 + Task 8 顺序 |
| single-flight per-sub 共享结果(I-1)| Task 1 定 + Task 5 |
| `list_jobs` 用 read() 投影 + spec 缺失 fail-closed(I-2)| Task 7 |
| `SessionData.csrf` 字段 + 登录一次写(I-3)| Task 3 + Task 4 |
| 刷新失败→清 cookie+401(I-4)| Task 5 |
| logout 需 CSRF(C-3)| Task 6 + runbook 验收3 |

前端(serve dist + React 控制台)= Plan 7。

> **C-1 是 BFF 命门 / 红线验收项**:BFF 全部安全收益 = "token 不进浏览器 + 客户端不能自带 bearer"。proxy 只要有一条回退客户端 authorization 的路径,BFF 即退化为"带登录页的透传反代"。该负向测试进 Verification Protocol。

## 自审记录

- 占位符:无 TBD;refresh 策略/cookie 体积是 **Task 1 探查产出**(带决策规则:rotation 开→single-flight、>4KB→降级),非猜测(宪法 §3.4)。
- 类型一致:`SessionData`/`SessionCodec`/`list_jobs`/`Job`/`JobList`(契约同源)签名贯通;`enterprise_of` 复用 `_scaffold`。
- 分层:BFF 在 services 层 gateway 内;`gateway/bff/` 与反代物理隔离(C-3);proxy bearer 改取 `request.state`,杜绝客户端伪造。
- 隔离:`GET /v1/data/jobs` 经 `can()` 过滤(I-1),不裸暴露跨企业;会话→bearer 后下游仍各自验签(纵深不变)。
- 安全:BFF 客户端无 ROPC + 窄回调(C-4);prod secret/realm 加固列 DoD 硬门;吊销窗口≤5min 登记风险(C-2)。
- ROPC 取舍:新增 `lite-ai-web` 给 BFF(无 ROPC);`gateway` 客户端 ROPC 保留给测试/ops —— 不破坏既有集成测试,prod 关 ROPC 已升格 ADR-019 登记要求(M-1)。
- **product-architect 复审(2026-06-19)采纳**:C-1(proxy 删 authorization 转发 + 伪造 bearer 负向红线测试)、C-2(中间件两阶段 + 刷新随当前响应 Set-Cookie + 注册顺序)、C-3(logout 需 CSRF,runbook 对齐)、I-1(single-flight per-sub 共享结果)、I-2(list_jobs 用 read() 投影 + fail-closed)、I-3(SessionData.csrf 字段)、I-4(刷新失败→清 cookie+401)、M-1(prod 加固升格 ADR)、M-2(TTL>5min 不可调则 escalate)、M-3(/auth/me 解会话内 access,不存 id_token)—— 已逐条落到对应 Task。

---

## 手动验收 runbook(实现完成后照此验证)

> 原则(宪法 §3.2):证据先于断言。zsh 整段粘贴报 `parse error near '#'` 先 `setopt interactivecomments`;改服务后 `make down && make up`(避陈旧进程)。

**前置:** `make up`(含 gateway BFF env);浏览器可达 Keycloak `:8080` 与 gateway `:8090`。

**验收 1 — 真浏览器 OIDC 全链路**
```bash
open http://localhost:8090/auth/login     # 跳 Keycloak 登录页(lite-ai-web 客户端)→ 用 alice 登录 → 跳回 /
# 浏览器开发者工具:确认有 HttpOnly `session` cookie + 非 HttpOnly `csrf_token` cookie
```
期望:登录后回到 `/`;`session` cookie(HttpOnly/SameSite=Lax)在;`/auth/me` 返回 alice + csrf。

**验收 2 — 会话调真服务(curl 复用浏览器 cookie 或脚本化)**
```bash
# 用浏览器 cookie 或脚本拿到 session cookie 后:
curl -fsS -b "session=<COOKIE>" http://localhost:8090/auth/me                          # A 返 user+csrf
curl -fsS -b "session=<COOKIE>" http://localhost:8090/v1/data/jobs                      # B 列本组作业(can() 过滤)
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8090/v1/data/jobs             # C 无会话 → 401
CSRF=<从 csrf_token cookie 读>
curl -s -o /dev/null -w "%{http_code}\n" -b "session=<COOKIE>" -X POST \
  -H "content-type: application/json" -d '{"dataset":"cc3m","group_id":"g-0001","tar_dir":"/tmp/tars"}' \
  http://localhost:8090/v1/data/prepare                                                 # D 缺 X-CSRF-Token → 403
curl -fsS -b "session=<COOKIE>" -H "X-CSRF-Token: $CSRF" -X POST \
  -H "content-type: application/json" -d '{"dataset":"cc3m","group_id":"g-0001","tar_dir":"/tmp/tars"}' \
  http://localhost:8090/v1/data/prepare                                                 # E 带 CSRF → 202
```
期望:A=alice+csrf;B=本组作业列表(经 can());C=`401`;D=`403`(CSRF 拦截);E=`202`(下游收到会话注入的 Bearer)。**这就是出口⑤ BFF 侧验收证据(GUI 侧 = Plan 7)。**

**验收 3 — 登出**(C-3:logout 需 CSRF)
```bash
CSRF=<从 csrf_token cookie 读>
curl -s -i -b "session=<COOKIE>" -H "X-CSRF-Token: $CSRF" -X POST http://localhost:8090/auth/logout | grep -i set-cookie  # session Max-Age=0
curl -s -o /dev/null -w "%{http_code}\n" -b "session=<COOKIE>" -X POST http://localhost:8090/auth/logout                 # 缺 CSRF → 403
```
期望:带 CSRF→`session`/`csrf_token` cookie 被清(Max-Age=0),旧 cookie 再打 `/v1/data/jobs`→401;缺 CSRF→`403`。

**收尾:** `make down`。
> **prod 加固提醒(DoD 硬门)**:`lite-ai-web` secret 走 secret 管理、回调/webOrigins 用 prod 域名、`gateway` 客户端 prod 关 ROPC、cookie `Secure` 开。
