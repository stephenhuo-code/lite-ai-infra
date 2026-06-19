# BFF OIDC 探查事实记录(Task 1 / 宪法 §3.4 探查优先)

> 来源:对真 Keycloak 26.6.2(`deploy/dev/docker-compose.yml` + `realm-lite-ai.json`)实测,脚本 `probe.sh`。
> 日期:2026-06-19。**实现以本文件为准,禁止把猜测写进 Task 3–8。**

复现:`make dev-up` 后 `uv run bash spikes/bff_oidc/probe.sh`。

---

## 1. Token 大小 / access TTL(probe §1)

| 项 | 实测值 |
|---|---|
| access_token | **1078 字节**(alice,单组 `/e-0001/g-0001/members`) |
| refresh_token | **642 字节** |
| id_token | 1090 字节(**BFF 不存 id_token**,M-3:`/auth/me` 解会话内 access) |
| **access TTL(`expires_in`)** | **300 秒 = 5 min** |
| access claims | `groups=['/e-0001/g-0001/members']`、`exp-iat=300`、`azp=gateway`、`aud=None` |

**TTL 研判(M-2):** realm 默认 `accessTokenLifespan = 300s = 5min`,**恰 ≤ 5min**,满足 ADR-019「吊销窗口 ≤5min」缓解。
→ **无需 escalate owner**;无需改 realm TTL。prod 维持 ≤5min(DoD 硬门已列)。

## 2. refresh rotation 行为(probe §2)—— I-2 死结判定

实测(同一 refresh token 连刷两次):
- 第 1 次刷新:成功,**新 refresh token ≠ 旧**(KC 每次签发新 refresh)。
- 第 2 次刷新(**复用旧 refresh token**):**仍成功拿到 access**。

**结论:dev realm「Revoke Refresh Token」默认关 → 旧 refresh 用后不失效 → rotation 未强制执行。**
并发请求各拿旧 refresh 去刷都成立,**无「旧 refresh 失效→随机登出」死结(I-2 不触发)**。

**refresh 策略决定:**
- 严格按本实测:dev 可**直刷**(rotation 关)。
- **但实现选 single-flight per-`sub`(`asyncio.Lock` + lock 内 double-check)**,理由:
  1. **prod-parity 防御**——DoD prod 加固可能开「Revoke Refresh Token」(rotation 真启),届时直刷即触发 I-2 死结;single-flight 在 rotation 开/关**两种 regime 下都正确**,代价可忽略(单副本进程内锁)。
  2. 即便 rotation 关,single-flight 也避免同一 `sub` 短时重复刷新打 KC(省调用)。
  - 这是 I-1 要求的实现;**不是猜测**——是「实测 rotation 关 + 防 prod 开」的显式取舍,记此处。

## 3. cookie 体积(probe §3)—— 单 cookie < 4KB 判定

`{access_token, refresh_token, expires_at, csrf}` Fernet 加密:
- 明文 JSON:1842 字节
- **Fernet 密文(cookie 值):2552 字节** + `session=` 前缀 ≈ **2560 字节**
- **< 4096(单 cookie 上限)→ 单加密 cookie 方案成立,无需降级。**

**最坏样本说明:** 本样本为单组用户。多组用户的 `groups` full-path claim 会增大 access_token →
cookie 同步增大。当前 headroom ≈ 4096−2560 ≈ **1500 字节**(约可容纳十余个组的 full-path)。
**若未来某用户组数使 cookie > 4KB → 降级方案**(已登记,Task 3 留 seam):
只存 refresh + 用 refresh 现换 access(不存 access);或拆双 cookie。v1 单企业小规模不触发。

## 4. Authorization Code + PKCE 端到端(probe §4)

curl 脚本化 alice 登录走通:
- authorize(`code_challenge` S256)→ 登录表单 → 302 callback **带 `code` + `state` 回显匹配**。
- `code` + 正确 `code_verifier` 换 token:**成功**,`expires_in=300`。
- **错误 `code_verifier` 换 token:`invalid_grant`(被拒)→ PKCE 校验生效。**

→ Task 4 的 authorize URL 构造 / PKCE S256 / token 交换路径**与实测一致**;
完整真浏览器 code 流由人工 runbook(Task 8 验收 1)复验。

---

## 对 Task 3–8 的硬约束(实测产出)

1. **access TTL=5min** 已满足,`SessionData.expires_at = now + expires_in`(Task 3/4)。
2. **refresh:single-flight per-`sub` + lock 内 double-check**(Task 5 I-1),理由见 §2。
3. **单加密 cookie 成立**(2560<4096),Task 3 不降级;>4KB 降级规则留注释 seam。
4. **id_token 不入会话**(M-3),`/auth/me` 解会话内 access claims。
5. PKCE S256 + state 校验为 callback 硬门(Task 4 I-3)。
