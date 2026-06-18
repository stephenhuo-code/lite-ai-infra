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

1. **出口⑤ 重定义**:由"SDK/CLI 可调"改为 **"真 GUI 经 API 端到端调通"**(图形客户端登录 → 经 gateway 调服务 → 完成数据域核心流)。`laictl`(Plan 6 草稿,commit 9a70c18)**推迟**为后续 ops/自动化/CI 工具,**不删**(契约/device-flow 分析沉淀复用)。

2. **认证 = BFF**(owner 决策)。gateway 由"薄反代壳"升级为 **BFF**:服务端 OIDC Authorization Code(+PKCE)、`/login`·`/callback`·`/logout`、服务端会话、会话→下游 bearer、CSRF 防护。**前端永不接触 token**(比 SPA-PKCE 安全,终态形态)。

3. **会话存储(v1 无 PG,ADR-013)= 无状态加密 cookie**(owner 采纳推荐)。token 装进**签名+加密 cookie**(AEAD,如 Fernet),无服务端会话存储、**零新基础设施**。置于**会话存储 seam** 后,S2 可换服务端存储(Redis/PG)。
   - 代价:无中心化会话吊销(依赖 token 生命周期 / Spike A);cookie 体积上限;刷新靠 refresh-token-in-cookie 或重登。
   - 否决:进程内内存(单副本、重启丢)、Redis(新基础设施)——均不适 v1。

4. **前端 = React + Vite**(owner 决策),置 `frontend/` 子目录(node 工具链);dev 经 vite 起,**生产部署留 S2c**。把中保真原型(`docs/superpowers/prototypes/2026-06-16-data-domain-midfi.html`)做成真调 BFF 的应用。

5. **强制后端补契约**:`GET /v1/data/jobs`(backlog #1,列作业 + 分页/状态过滤)加进 data-pipeline(GUI 作业页需要)。其余 backlog 按 GUI 各页需要逐步加(#2 分页等);**"数据集上传"页(#11)本轮可推迟**(上传端点是独立较大件)。

6. **路线重排**:GUI(BFF + 前端)现在做、关 S1 出口⑤;**S2a(10TB 放大 + Gravitino HA)、S2b(Embedding/ANN)顺延到 GUI 之后**(承 ADR-014:出口重排走 ADR)。

7. **计划拆分**(编号承口径 A):
   - **Plan 6 → BFF 后端**:gateway OIDC 登录/会话/登出(无状态加密 cookie)+ CSRF + `GET /v1/data/jobs`(#1)。
   - **Plan 7 → React/Vite 前端**:数据域控制台(登录跳转 + 数据目录/数据管线/作业/我的账户;数据集上传页按 #11 决定是否纳入)。
   - **Plan 8 → Dev Workspace docker**(出口④ stretch,顺延一位)。
   - 原 CLI Plan 6 文档标 **deferred**。

## Consequences

**正面**:交付真正的终端用户产品;BFF 是安全/终态认证模型(token 不进浏览器);React+Vite 可维护;API 仍是稳定核心(GUI 只是又一个客户端,services 不动业务逻辑)。

**负面 / 已知**:
- 体量远大于 CLI;**等于把 S2c 提前**,S2a/S2b 顺延。
- Python 仓库引入 **node 工具链**(隔离在 `frontend/`)。
- **无状态 cookie**:无中心会话吊销(token 生命周期依赖);cookie 体积限制;刷新需处理。
- BFF 是 **confidential OIDC 客户端**(持 client secret),需管密钥;Keycloak realm 需对应客户端配置(回调 URI)。
- **CORS**:若前端经 gateway 同源服务/反代,可免 CORS;dev 若异源(vite :5173 ↔ gateway :8090)需配 CORS 或 vite 代理。
- GUI 受当前契约面限制,本轮拉入 #1(列作业);其余 backlog 渐进补。

## Alternatives considered

- **保留 CLI(Plan 6)关出口⑤,GUI 留 S2c** —— owner 否决(要现在就有 GUI)。
- **SPA + OIDC PKCE(无 BFF)** —— 更轻但 token 在浏览器;否决,选 BFF(安全 + 终态)。
- **会话存储:进程内 / Redis** —— 否决(单副本/新基础设施);选无状态加密 cookie。
- **Vanilla JS 前端** —— 否决(终态产品不可维护);选 React+Vite。
