# Design(设计):S1 Plan 8 — 数据域控制台(React/Vite 前端)

> 设计层(HOW)。引用既有家、不复制:契约→`contracts/openapi/`;决策→ADR-019/ADR-020;后端→Plan 6 BFF、Plan 7 上传后端。

## 架构
- **纯前端**(#11 拆分后):上传后端能力已拆为 **Plan 7(数据上传后端,先行)**;Plan 8 是其图形消费者。
- **`frontend/` React + Vite SPA**(ADR-019 owner 决策),node 工具链隔离在 `frontend/` 子目录。
- **同源,前端不持 token**(对齐 BFF):
  - **dev**:vite dev server(:5173)用 **proxy** 把 `/auth/*`、`/v1/*` 转发到 gateway(:8090)→ 浏览器视角同源、带 BFF 会话 cookie、免 CORS。
  - **prod**:`vite build` → `frontend/dist`,由 **gateway 静态服务**(StaticFiles + SPA history fallback 到 `index.html`)→ 天然同源。
- 前端是 BFF 的纯客户端:不直连 identity/metadata/data-pipeline,全部经 gateway。**唯一例外(ADR-020 §5):上传字节直 PUT 到 OSS endpoint(非同源数据面)**;控制面(请求上传/complete/列)仍经 gateway。

## 核心流程
- **启动鉴权**:应用加载 → `GET /auth/me`;200→拿 user+csrf 渲染;401→`window.location = "/auth/login"`(BFF 跑 OIDC code+PKCE → 回 `/`)。
- **CSRF**:请求层拦截器对变更方法自动加 `X-CSRF-Token`(读非-HttpOnly `csrf_token` cookie)。
- **作业轮询**:创建作业(POST `/v1/data/prepare`)→ 进"数据管线";详情页对 `GET /v1/data/jobs/{id}` 轮询,按 `terminal` 停。
- **登出**:POST `/auth/logout`(带 CSRF)→ 清会话 → 回登录态。

## 数据集上传页(#11,消费 Plan 7 契约;机制 ADR-020 已定)
- **前端三段流程**(Plan 7 契约):① 调 `POST /v1/data/raw`(经 gateway)拿 presigned URL/分片 URL + raw_id → ② 浏览器**直 PUT 字节到 OSS**(单 / 分片并行 + 进度 + 重试)→ ③ 调 `POST /v1/data/raw/{id}/complete` 标完成 → 列表见 `ready`。
- **隔离/审计/key 构造全在 Plan 7 后端**(ADR-020 C-1/C-2):前端**不拼 key、不做授权判定**;越权由后端 403、前端友好提示。
- **presigned 过期**:PUT 失败 → 前端重新请求 presign(TTL≤15min)。
- **大文件**:分片直传显示进度;断点续传(失败片重传)。

## 数据模型(前端薄类型,镜像契约)
- `Me { user, is_platform_admin, memberships[], csrf }`、`Dataset {...}`、`Job { id,status,terminal,rows_*,lance_uri,error }`、`PrepareJobRequest {...}` —— 字段以 `contracts/openapi/*` 为准(生成或手写,见技术选型)。
- **无前端持久状态**(会话在 BFF cookie);仅内存态(当前用户、列表缓存)。

## 授权与安全
- **前端零授权**:列表/详情只渲染后端 `can()` 过滤后的数据(FR-004);不在前端做企业/组判定。
- **token 不进前端**(FR-006):access/refresh 在 BFF HttpOnly 会话 cookie;前端碰不到。
- **CSRF**:双提交——前端读可读 `csrf_token` cookie → 加 `X-CSRF-Token` 头(BFF 校验)。
- **威胁(登记)**:XSS 拿不到 token(HttpOnly),但能读 `csrf_token` cookie 并借浏览器会话发请求 → XSS 下 CSRF 防护被削弱(残留风险,与"无状态 cookie"同级登记;缓解=CSP/严格转义,S2c 强化)。

## 非功能(NFR)
- **同源**:dev=vite proxy、prod=gateway serve dist → 免 CORS、cookie 不跨站(SameSite=Lax 成立)。
- **dev/prod parity**:dev proxy 同源 ≈ prod gateway-serve 同源;**出口⑤ 在同源拓扑验收**(ADR-019 I-4)。
- **构建产物**:`frontend/dist` 由 gateway `StaticFiles` 挂载 + catch-all 返回 `index.html`(SPA 路由 fallback),且**不拦截** `/auth/*`、`/v1/*`、`/docs`。
- **性能/规模**:列表先最简(后端分页 #2 到位后再接);轮询用固定间隔(可退避)。

## 依赖与引用
- **契约**:`contracts/openapi/{identity-org,metadata,data-pipeline}.yaml`(经 gateway 透传;前端类型以此为源)。
- **决策(ADR)**:`ADR-019`(BFF + React/Vite + gateway serve dist + 同源验收)· **`ADR-020`(上传 presigned 直传、§5 数据面非同源豁免)**。
- **UI 第一消费者**:`docs/superpowers/prototypes/2026-06-16-data-domain-midfi.html`(信息架构/屏/流程蓝本,已反推契约 ✓ —— DoR ② 满足)。
- **后端**:Plan 6 BFF(`/auth/login|callback|logout|me`、会话→bearer、CSRF、`GET /v1/data/jobs`)· **Plan 7 上传后端(`POST /v1/data/raw`、`POST /v1/data/raw/{id}/complete`、`GET /v1/data/raw`)—— 前置依赖,需契约冻结后本 plan 方可写 tasks**。

## 技术选型理由
- **React + Vite**:ADR-019;Vite dev proxy 直接解决同源。路由 `react-router`;请求用 `fetch` + 薄拦截器(CSRF/401)。
- **前端类型**:`openapi-typescript` 从契约生成 TS 类型(契约同源,首选)**或**手写薄类型(更轻)—— **待探查决策**(见 DoR #4)。

## ★ DoR 自检(进 tasks 前过门;三态:已决定 / 显式推迟+理由 / 待探查+探针+决策规则)
- [x] **1 范围与出口**:**已决定** —— 关出口⑤;验收=浏览器登录→列数据集→建作业→轮询终态→上传数据集→登出(可证伪)。上传后端已拆 Plan 7。
- [△] **2 接口契约**:**读/作业端点已决定;上传契约依赖 Plan 7 冻结** —— 读+作业端点都在(Plan6 BFF + metadata + `GET /v1/data/jobs`),UI 第一消费者=midfi 原型 ✓;上传三端点形态由 **ADR-020 定 + Plan 7 冻结** → **本 plan DoR 前置 = Plan 7 契约就绪**(顺序依赖,非未知)。
- [x] **3 数据模型**:**已决定** —— 前端薄类型镜像契约;RawDataset 字段随 Plan 7 契约;无前端持久态。
- [ ] **4 外部依赖事实**:**待探查(本 plan Task 1 探针)** —— 前端工具链:React+Vite 脚手架 / vite dev proxy 同源 / gateway StaticFiles+SPA fallback 不吃 `/auth /v1` / 类型生成方式。**决策规则**:proxy 实测带会话 cookie 调通 `/auth/me` → 用 vite proxy;StaticFiles+catch-all 后 `/auth /v1 /docs` 仍达且未知路由回 index → 采纳;`openapi-typescript` 能从 yaml 生成可用类型 → 用生成,否则手写薄类型。
- [x] **5 行为·边界·并发·威胁**:**已决定** —— 401→登录;CSRF 自动带;按 `terminal` 轮询;上传 presigned 过期重取/进度/重试;XSS 残留登记。
- [x] **6 NFR**:**已决定** —— 同源/parity/dist-serve/HttpOnly token;上传数据面非同源(ADR-020 §5)、隔离/审计在 Plan 7 后端;富分页推迟。
- [x] **7 验收与测试策略**:**已决定** —— build+lint + 真 BFF e2e(核心流 + 上传三段)+ runbook(writing-plans 出)。
- [x] **8 关键决策留痕**:**已决定** —— ADR-019(BFF/React/serve-dist)+ **ADR-020(上传机制)** 均 Accepted;前端无新增地基决策(类型生成 vs 手写按 Task1 探针结论)。

**结论(#11 拆分后)**:8 项中 6 项已决定、#4 前端工具链待探查(带决策规则,本 plan Task 1 即探针)、**#2 上传契约为顺序依赖(待 Plan 7 冻结,非未知 TBD)** → **no-TBD**。**过门条件 = Plan 7 上传契约冻结**;满足后进 `superpowers:writing-plans`。建议:**Plan 7 先走 writing-plans→执行→冻结契约→合并,再启动本 Plan 8。**
