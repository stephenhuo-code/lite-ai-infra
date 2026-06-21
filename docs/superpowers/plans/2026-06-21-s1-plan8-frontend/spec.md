# Spec(需求):S1 Plan 8 — 数据域控制台(React/Vite 前端)

> 需求层(WHAT / WHY)。禁技术栈/契约 schema/实现。

## 关联出口 / Sprint
- 出口:**S1 出口⑤ —— 真 GUI 经 API 端到端调通**(ADR-019)。前端是 BFF/契约的图形客户端;关闭出口⑤。
- Sprint:S1(已延长,ADR-019)。前序:Plan 6 BFF ✅、**Plan 7 数据上传后端**(承 ADR-020;上传页消费其冻结契约)。

## Goal & 价值
- 把中保真原型 `docs/superpowers/prototypes/2026-06-16-data-domain-midfi.html` 做成**真调 BFF 的数据域控制台**:登录后经 gateway/BFF 调真服务,完成数据域核心流(看数据集 / 提交并跟踪作业 / 看账户)。
- 价值:首个客户拿到可点的产品界面;证明"契约/服务可被真实图形客户端端到端调通"。

## 范围
- **In**:登录跳转(经 BFF)· 我的账户/组织 · 数据目录(列表 + 详情)· 数据管线(作业列表 + 状态/轮询)· 创建作业(提交)· 应用外壳(侧栏导航/顶栏/登出)· **数据集上传页(原型 #11):消费 Plan 7 上传后端契约,presigned 直传 OSS + 进度/重试**(owner 决:本轮纳入)。
- **Out**:**上传后端端点**(已拆为 Plan 7,先行)· 高保真视觉稿(spec 后)· Embedding/检索界面(S2b)· Enterprise Provisioner(S2c)· 高级富交互/移动端适配。
- **推迟(vN+/backlog,带理由)**:富分页/搜索 UI 依赖后端 #2,先做最简。

> **范围澄清(#11 拆分后)**:Plan 8 **回归纯前端** —— 上传后端能力已拆为 **Plan 7(数据上传后端,ADR-020 presigned 直传,先行)**。本 plan 的上传页是 Plan 7 契约的**图形消费者**:走"请求上传→直传 OSS→complete"三段,字节直传 OSS(数据面非同源,ADR-020 §5 豁免)。**前置依赖:Plan 7 契约冻结**。

## 用户场景 & 验收(可证伪)
- **场景 1 登录**:作为用户,我要登录才能用平台。
  - **AC-1** Given 未登录 When 访问任一受保护视图 Then 自动跳 `/auth/login`(经 BFF→Keycloak→回应用),回来后顶栏显示当前用户。
  - **AC-2** Given 已登录 When 点登出 Then 会话清除、回到登录态;旧会话再访问受保护视图→跳登录。
- **场景 2 数据目录**:作为组成员,我要看本组数据集。
  - **AC-3** Given 已登录 When 打开"数据目录" Then 看到**本组(can() 过滤)**数据集列表;点一项看详情(owner/scope/位置/创建)。
- **场景 3 数据管线/作业**:作为用户,我要提交数据准备作业并跟踪。
  - **AC-4** Given 已登录 When 在"创建作业"提交 Then 返回作业(202),作业出现在"数据管线"列表。
  - **AC-5** Given 有运行中作业 When 在作业详情停留 Then 状态自动轮询到**终态**(succeeded/failed),终态展示产物/错误。
- **场景 4 我的账户**:**AC-6** Given 已登录 When 打开"我的账户" Then 显示 user、企业(隐藏标识)、组、角色(来自 `/auth/me`)。
- **场景 5 数据集上传(#11,消费 Plan 7 契约)**:作为组成员,我要上传原始数据供后续清洗。
  - **AC-7** Given 已登录 When 在"数据集"上传文件(选本组)Then 前端走 Plan 7 三段(请求上传→**presigned 直传 OSS**→complete),成功后原始数据出现在列表(`ready`),可在"创建作业"里被选为源。
  - **AC-8** Given 上传大文件 When 上传中 Then 显示进度(分片直传);失败可重试;presigned 过期可重新请求 presign。
  - 边界:越权(后端 403)→ 友好提示不签 URL;超大/中断 → 明确提示。
- **边界/异常**:会话过期(401)→ 跳登录;变更请求缺 CSRF → 前端自动带,不让用户撞 403;跨组数据 → 列表里不出现(后端过滤);后端 503/网络错 → 友好提示不白屏。

## 功能需求(可测)
- **FR-001** 前端 MUST 经 **gateway/BFF 同源**调 API;MUST NOT 直连下游服务、MUST NOT 自行向 Keycloak 换 token。**例外(ADR-020 §5):仅上传字节这一数据面可直 PUT 到 OSS(非同源)**——控制面(请求上传/complete/列)仍同源经 gateway。
- **FR-002** 未认证访问受保护视图 MUST 跳 `/auth/login`(或 401 拦截后跳)。
- **FR-003** 所有变更请求(POST/PUT/DELETE/PATCH)MUST 带 `X-CSRF-Token`(取自 `csrf_token` cookie / `/auth/me`)。
- **FR-004** 列表/详情 MUST 只展示后端 `can()` 返回的数据;前端 MUST NOT 自做授权判定。
- **FR-005** 作业提交后 MUST 能轮询状态到终态(按 `terminal` 判,而非状态字符串匹配)。
- **FR-006** MUST NOT 在前端存储/暴露 access/refresh token(凭 BFF HttpOnly 会话 cookie)。
- **FR-007** 前端上传 MUST 走 Plan 7 三段契约(请求上传→presigned 直传→complete);**隔离/审计由 Plan 7 后端保证**(前端不自做授权判定);前端 MUST NOT 自行拼 OSS key。
- **FR-008** 前端上传 MUST 显示进度、失败可重试、presigned 过期可重取;上传产物(`ready`)MUST 可在"创建作业"里被选为源。

## 关键实体(概念级)
- **Me**:当前用户 + 组织上下文(user、企业(隐藏)、组、角色、csrf)。
- **Dataset**:数据目录里的已处理数据集(名/组/owner/scope/位置/创建)。
- **Job**:数据准备作业(id/状态/terminal/行数/产物 URI/错误)。
- **PrepareJobRequest**:创建作业的输入(数据集/组/源/算子)。
- **RawDataset**:上传的原始数据(名/组/OSS `raw/` 路径/大小/上传状态)—— 新增,#11。

## 未决
- 无静默 TBD。上传机制已由 **ADR-020 拍板**(presigned 直传);上传契约由 **Plan 7** 冻结 —— 本 plan 的 DoR 前置依赖 = **Plan 7 契约就绪**(见 design.md DoR #2)。
