# Design(设计):S1 Plan 8 — 数据域控制台(React/Vite 前端)

> 设计层(HOW)。引用既有家、不复制:契约→`contracts/openapi/`;决策→ADR-019/ADR-020;后端→Plan 6 BFF、Plan 7 上传后端。

## 架构
- **前端为主 + 一处后端小补**:上传后端已是 Plan 7;本 plan 主体是前端控制台,**外加 metadata `Dataset` 加 3 字段**(format/num_samples/size_bytes;契约 + metadata-service + data-pipeline 注册写入)让数据集页显真值。
- **照高保真原型搭**:`docs/superpowers/prototypes/2026-06-22-data-domain-hifi.html`(IA/视觉/交互基线,owner 确认)。
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

## 屏与数据来源(照原型;C-1 降级后)
- **数据集**(US1):列表来自 metadata `GET /v1/catalogs/{c}/schemas/{s}/datasets` 与上传的 Plan 7 `GET /v1/data/raw`(两类资产并列呈现,raw 标"原始");列 = 名称/描述/格式/样本数/大小/创建人/操作(详情)。**列不含模态/标签**(后端无字段源,C-2)。**上传**=本页弹窗,走 Plan 7 三段。**不出现用户组列**。**上传得到的 raw 在 S1 不作为建作业入口**(S2a)。
- **数据目录(Catalog Explorer · 两栏)**:左树 = `GET /v1/catalogs` → `…/schemas` → `…/datasets`,层级标签对用户呈现为 **企业 → catalog → schema → 数据集**(可折叠);右详情 = 选中 schema 的数据集清单(名/owner/格式/注册时间/scope)+ 概览 + "关于此 Schema"(状态/owner/catalog)。Tab 仅 **概览/详情**。
- **应用外壳**:侧栏**可折叠**;顶栏企业名 + 用户菜单(登出)。**全界面不渲染内部标识(e-/g- ID)**。
- **创建作业(US4)**:表单提交 `POST /v1/data/prepare`,**源 = 指定数据位置**(S1 = `tar_dir`,运维预置;过渡形态)。**不做"从数据集/目录一键预选源"**(原型该入口对应 raw→prepare 桥,= S2a)。
- **作业成功/失败(US4/US5)**:数据管线列表按状态(含"失败")筛选;详情用 `GET /v1/data/jobs/{id}` 展示终态/产物 URI/`error`;**产物只展示位置不提供下载**(下载=vN+)。
- **空状态(FR-011)**:列表/目录无可见数据时渲染明确空态 + 下一步引导。
- **原型中以下控件 S1 不实现(照原型搭时务必去掉)**:数据集"另存为/SQL查询"、catalog 详情"共享/注册/+添加标签"、catalog 树"新建"、数据集详情"用于创建作业"按钮、数据助手栏(已删);理由见 spec Out(管理/注册/共享/一键发起 = vN+ / S2a)。

## metadata 新字段(契约任务,Task 1 冻结)
- metadata `Dataset` + `RegisterDataset` 加 **`format`(Lance/原始/…)、`num_samples`(行数)、`size_bytes`**(均 nullable,0.x 加法不破现有)。
- metadata-service:注册接受 + 读返回这 3 字段;data-pipeline 产出 Lance 后注册时写入(从 Lance 读 count/size)。前端缺值优雅占位(FR-009)。

## 数据模型(前端薄类型,镜像契约)
- `Me { user, is_platform_admin, memberships[], csrf }`、`Dataset {…+format,num_samples,size_bytes(Task1 新增)}`、`RawDataset {…oss_key,status}`、`Job { id,status,terminal,rows_*,lance_uri,error }`、`PrepareJobRequest { dataset,group_id,tar_dir,… }`(源=tar_dir,S1)—— 字段以 `contracts/openapi/*` 为准。
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
- **UI 基线(第一消费者)**:`docs/superpowers/prototypes/2026-06-22-data-domain-hifi.html`(高保真,owner 迭代确认;IA/视觉/交互蓝本,反推出 metadata 3 字段缺口 —— DoR ② 满足)。
- **后端**:Plan 6 BFF(`/auth/login|callback|logout|me`、会话→bearer、CSRF、`GET /v1/data/jobs`)· **Plan 7 上传后端(`POST /v1/data/raw`、`POST /v1/data/raw/{id}/complete`、`GET /v1/data/raw`)—— 前置依赖,需契约冻结后本 plan 方可写 tasks**。

## 技术选型理由
- **React + Vite**:ADR-019;Vite dev proxy 直接解决同源。路由 `react-router`;请求用 `fetch` + 薄拦截器(CSRF/401)。
- **前端类型**:`openapi-typescript` 从契约生成 TS 类型(契约同源,首选)**或**手写薄类型(更轻)—— **待探查决策**(见 DoR #4)。

## ★ DoR 自检(进 tasks 前过门;三态:已决定 / 显式推迟+理由 / 待探查+探针+决策规则)
- [x] **1 范围与出口**:**已决定(C-1 降级)** —— 关出口⑤=GUI 经 API 驱动数据域各能力(登录→列数据集→浏览目录→上传入库→建作业(源=tar_dir)→跟踪/排障→账户),dev 同源拓扑验收。**"上传 raw 直接建作业/一键发起" 显式推迟 S2a**(契约无 raw→prepare 桥)。
- [x] **2 接口契约**:**已决定** —— 消费端点齐:Plan6 BFF(`/auth/*`)+ metadata(`catalogs/schemas/datasets`、`/me/orgs`)+ data-pipeline(`/v1/data/jobs`、`/v1/data/prepare`(源 `tar_dir`)、Plan 7 上传三端点,**已冻结合并**)。本 plan **新增 metadata 3 字段**(format/num_samples/size_bytes)= 契约先行任务(Task 1)。模态/标签无后端源 → 不渲染(C-2)。高保真原型为第一消费者 ✓。
- [x] **3 数据模型**:**已决定** —— 前端薄类型镜像契约;RawDataset 字段随 Plan 7 契约;无前端持久态。
- [ ] **4 外部依赖事实**:**待探查(本 plan Task 1 探针)** —— 前端工具链:React+Vite 脚手架 / vite dev proxy 同源 / gateway StaticFiles+SPA fallback 不吃 `/auth /v1` / 类型生成方式。**决策规则**:proxy 实测带会话 cookie 调通 `/auth/me` → 用 vite proxy;StaticFiles+catch-all 后 `/auth /v1 /docs` 仍达且未知路由回 index → 采纳;`openapi-typescript` 能从 yaml 生成可用类型 → 用生成,否则手写薄类型。
- [x] **5 行为·边界·并发·威胁**:**已决定** —— 401→登录;CSRF 自动带;按 `terminal` 轮询;上传 presigned 过期重取/进度/重试;XSS 残留登记。
- [x] **6 NFR**:**已决定** —— 同源/parity/dist-serve/HttpOnly token;上传数据面非同源(ADR-020 §5)、隔离/审计在 Plan 7 后端;富分页推迟。
- [x] **7 验收与测试策略**:**已决定** —— build+lint + 真 BFF e2e(核心流 + 上传三段)+ runbook(writing-plans 出)。
- [x] **8 关键决策留痕**:**已决定** —— ADR-019(BFF/React/serve-dist)+ **ADR-020(上传机制)** 均 Accepted;前端无新增地基决策(类型生成 vs 手写按 Task1 探针结论)。

**结论(architecture-reviewer 复审采纳 + C-1 owner 拍板降级)**:7 项已决定;#4 前端工具链为带决策规则的探针(Task 2)。复审 Critical 已消解——C-1 闭环降级(raw→prepare 桥推 S2a)、C-2 模态/标签不渲染;I-1 原型 Out 控件已点名不实现、I-2 目录层级命名对齐 catalog→schema。范围诚实有界 → **no-TBD,DoR 可过**。
**Task 序(writing-plans)**:① metadata 3 字段契约+服务+pipeline 写入 ② 前端工具链探针 ③ 前端各屏(登录外壳/数据集+上传弹窗/数据目录两栏/数据管线+排障/创建作业/账户)④ 真 BFF e2e + 手动 runbook。
