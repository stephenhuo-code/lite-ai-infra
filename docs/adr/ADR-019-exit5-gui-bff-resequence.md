# ADR-019: 出口⑤ 从 SDK/CLI 改为真 GUI(BFF + React/Vite);路线重排,CLI 推迟

- 状态：Accepted（2026-06-18，owner）
- 决策人：owner
- 相关：ADR-002(Keycloak v1 单副本)、ADR-010(两级租户)、ADR-013(v1 无 PG;外部副作用走 reconcile)、ADR-014(出口重排先例:出口移交走 ADR)、ADR-018(作业调度 seam 模式);constitution §1(隔离)/§2.4(can())/§3.0.2(契约先行)/§3.1·§3.7(不静默改范围/契约)/§4(v1 容忍);S1 设计 spec §1 出口⑤、§6(S2c 前端 + §6.1 原型 backlog)、§9.3(计划序)

---

## Context

S1 出口⑤ 原定为 **"契约 SDK/CLI 可调"**(Plan 6 = `laictl`)。但 owner 的**终态产品是图形界面(GUI)**,不是 CLI。关键认识:**GUI 与 CLI 都只是同一套 API(gateway + 契约)的客户端**,平级;API/服务(S1 已交付)是稳定地基。出口⑤ 的本质是"**契约/API 能被真实客户端端到端调通**"——既可由 CLI 证明,也可由 GUI 证明。

owner 决策(2026-06-18 问答):**跳过 CLI,直接做真 GUI** 来满足出口⑤。这把原 S2c(前端 + BFF)提前到现在,并重排路线。

真 GUI 比 CLI 重,且会牵动后端:需真登录会话(BFF);"作业列表"页需要尚不存在的 `GET /v1/data/jobs`(原型 backlog #1);引入前端技术栈与构建链。按宪法 §3.1/§3.7 与 ADR-014 先例,**出口/范围重排必须走 ADR**。

## Decision

1. **出口⑤ 重定义**:由"SDK/CLI 可调"改为 **"真 GUI 经 API 端到端调通"**(图形客户端登录 → 经 gateway 调服务 → 完成数据域核心流)。`laictl` CLI **推迟**为后续 ops/自动化/CI 工具(计划文档已删,日后需要时重写;原草稿与契约/device-flow 分析见 git commit 9a70c18 留底)。

2. **认证 = BFF**(owner)。gateway 由薄反代壳升级为 BFF:服务端 OIDC Authorization Code + **PKCE**、`/auth/login`·`/auth/callback`·`/auth/logout`、服务端会话、会话→下游 bearer、CSRF。前端永不接触 token。
   - **(C-3,复审)本 ADR 显式修订 spec §9.1 的 BFF 定义**:由"纯路由聚合"扩为 **"OIDC 会话终结 + 路由聚合"**。OIDC/会话/CSRF 封装为 gateway 内独立模块 `services/gateway/bff/`(与反代物理隔离,为 v2 拆分留缝),**不**直接长进 `build_gateway`。
   - **(C-4,复审)realm 加固 = Plan 6 DoD 硬门**:`redirectUris` 由 `["*"]` 收窄到精确回调;关 `directAccessGrantsEnabled`(ROPC,CLI 已推迟);client secret 走 env/secret 管理,prod 不用 `dev-secret`。
   - **(I-3,复审)** `/auth/callback` 校验 `state` + PKCE `code_verifier`;所有副作用端点严格非 GET(SameSite=Lax 方成立);CSRF 双提交 token(cookie 副本 + `X-CSRF-Token` 头)。

3. **会话存储 = 无状态加密 cookie**(owner)。**(C-2,复审更正)这是为规避 Redis 新基建的独立工程取舍,非 ADR-013 要求**(ADR-013 的"无 PG"是业务数据/审计一致性,与会话无关);置于**会话存储 seam** 后,v2 可换 Redis/PG 获中心吊销。token 装 Fernet 加密 cookie(HttpOnly/SameSite=Lax)。
   - **吊销窗口(登记风险,owner 接受)**:无中心吊销 → 踢人/改组/降权在 access token 过期前不生效。**缓解 = access token TTL ≤ 5min + refresh 轮换**,把隔离风险窗口压到 ≤5min(写进风险表)。v2 服务端会话可即时吊销。
   - **(I-2,复审)refresh 并发死结**:无状态无服务端锁,并发请求同时刷新 + Keycloak refresh rotation → 互相失效 → 随机登出。**Plan 6 探查任务**用真 Keycloak 实测,定 single-flight(单副本进程内按 sub 加 asyncio.Lock)或关 rotation;**禁止把猜测写进计划**(宪法 §3.4 探查优先)。
   - 否决:进程内内存(单副本/重启丢)、Redis(新基建)。

4. **前端 = React + Vite**(owner),置 `frontend/`(node 工具链)。**(I-4,复审 + owner)gateway serve `frontend/dist`**(构建后静态资源由 gateway 直接 serve → 天然同源,消掉 CORS/cookie-domain/SameSite 跨域整类问题,更接近终态);dev 用 vite 代理同源。**出口⑤ 在同源拓扑上验收**。把中保真原型做成真调 BFF 的应用。

5. **强制后端补契约**:`GET /v1/data/jobs`(backlog #1)加进 data-pipeline。**(I-1,复审)契约先行 + 响应必经 `can()` 按企业/组过滤**(`JobStore` 加 `list_jobs(ctx,status,limit,offset)`,过滤在 service 层经 `can()` 做,**不**裸暴露跨企业的 `_all_status()`);分页 limit/offset;作业量上千需索引,**显式登记 vN+**。**"数据集上传"页(#11)本轮推迟。**

6. **范围/路线(C-1,owner=直接延长 S1)**:GUI(BFF+前端)**并入 S1、S1 工期顺延**;出口⑤ 由 GUI 关闭。**S1 范围显式扩张**(非 carry-over;spec §1 出口表 + §9.3 计划序同步)。S2a(10TB)/S2b(检索)顺延到 GUI 之后(承 ADR-014:重排走 ADR)。

7. **计划拆分**(编号承口径 A):
   - **Plan 6 → BFF 后端**:gateway OIDC 登录/会话/登出(无状态加密 cookie)+ CSRF + `GET /v1/data/jobs`(#1)。
   - **Plan 7 → 数据上传后端**(**2026-06-21 新增,承 ADR-020**):#11 上传字节落本组 `raw/` 的 presigned 直传后端(请求上传/complete/列原始数据三端点 + RawDataset + can()+审计)。**owner 决:#11 纳入本轮 → 上传后端拆为独立 plan,先于前端**。
   - **Plan 8 → React/Vite 前端**(原 Plan 7):数据域控制台(登录跳转 + 数据目录/数据管线/作业/我的账户 + **数据集上传页**,消费 Plan 7 上传后端契约)。
   - **Plan 9 → Dev Workspace docker**(原 Plan 8;出口④ stretch,再顺延一位)。
   - 原 CLI Plan 6 文档**已删**(推迟为后续 ops 工具,日后重写;commit 9a70c18 留底)。

## Consequences

**正面**:交付真正的终端用户产品;BFF 是安全/终态认证模型(token 不进浏览器);React+Vite 可维护;API 仍是稳定核心(GUI 只是又一个客户端,services 不动业务逻辑)。

**负面 / 已知**:
- 体量远大于 CLI;**S1 范围扩张、工期顺延**(owner:直接延长 S1);S2a/S2b 顺延到 GUI 之后。
- Python 仓库引入 **node 工具链**(隔离在 `frontend/`)。
- **无状态 cookie 无中心吊销**:踢人/改组在 access token 过期前不生效 → **吊销窗口 ≤ access TTL(≤5min)**(登记风险,owner 接受);cookie 体积上限(Plan 6 探查实测真 token 大小,token 带 groups full-path claim 多组用户可能膨胀)。
- BFF 持 **client secret**(confidential client),需密钥管理。**prod realm 加固(登记要求,非仅 Plan DoD;复审 M-1 升格)**:`lite-ai-web` secret 走 secret 管理(非 `dev-web-secret`)、`redirectUris`/`webOrigins` 用 prod 域名、`gateway` 客户端 **prod 关 ROPC**(dev 保留给集成测试)、cookie `Secure` 开。dev 用专用 `lite-ai-web`(窄回调、无 ROPC,C-4)。
- **refresh 并发刷新**需 single-flight 或关 rotation(I-2,探查实测定)。
- gateway 职责扩为 **"OIDC 会话终结 + 反代聚合"**(修订 §9.1);会话逻辑模块隔离,留 v2 拆分缝(C-3)。
- **同源 serving**(gateway serve `dist`)避开 CORS;出口⑤ 在同源拓扑验收(I-4)。
- GUI 受当前契约面限制,本轮拉入 #1(列作业);其余 backlog 渐进补。
- **Plan 6 可独立验收**(M-1):curl 跑通 OIDC code 全链路(`/auth/login` 302→KC→`/auth/callback` set-cookie→带 cookie 调 `/v1/data/jobs` 200→`/auth/logout` 清 cookie),不依赖 Plan 7 前端。

## 修订记录

- **2026-06-21(承 ADR-020 计划重排)**:owner 决"#11 数据集上传纳入本轮",上传后端拆为**独立 Plan 7(数据上传后端,先行)**;原 Plan 7 前端顺延为 **Plan 8**、原 Plan 8 Dev Workspace 顺延为 **Plan 9**(见 Decision §7 + ADR-020)。
- **2026-06-18(product-architect 隔离复审采纳)**:C-1 范围定性=直接延长 S1(已入 Decision §6 + Consequences);C-2 会话存储论证更正(独立取舍非 ADR-013 要求)+ ≤5min TTL + 吊销窗口登记;C-3 显式修订 spec §9.1 BFF 定义 + 会话逻辑模块隔离;C-4 realm 加固为 DoD 硬门;I-1 列作业 can() 过滤+分页;I-2 refresh 并发探查任务;I-3 callback state/PKCE + CSRF;I-4 gateway serve dist 同源验收。复审结论"需改后用",上述修订后方可作 Plan 6/7 地基。

## Alternatives considered

- **保留 CLI(Plan 6)关出口⑤,GUI 留 S2c** —— owner 否决(要现在就有 GUI)。
- **SPA + OIDC PKCE(无 BFF)** —— 更轻但 token 在浏览器;否决,选 BFF(安全 + 终态)。
- **会话存储:进程内 / Redis** —— 否决(单副本/新基础设施);选无状态加密 cookie。
- **Vanilla JS 前端** —— 否决(终态产品不可维护);选 React+Vite。
