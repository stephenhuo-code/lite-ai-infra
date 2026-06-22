# Spec(需求):S1 Plan 8 — 数据域控制台(React/Vite 前端)

> 需求层(WHAT / WHY)。禁技术栈/契约 schema/实现。

## 关联出口 / Sprint
- 出口:**S1 出口⑤ —— 真 GUI 经 API 端到端调通**(ADR-019)。前端是 BFF/契约的图形客户端;关闭出口⑤。
- Sprint:S1(已延长,ADR-019)。前序:Plan 6 BFF ✅、Plan 7 数据上传后端 ✅(契约已冻结)。
- **视觉/IA 基线**:高保真原型 `docs/superpowers/prototypes/2026-06-22-data-domain-hifi.html`(owner 迭代确认;ui-ux-pro-max 风格)。**Plan 8 照此原型搭实现。**

## Goal & 价值
- 把高保真原型做成**真调 BFF 的数据域控制台**:登录后经 gateway/BFF 调真服务,完成数据域核心流(数据集管理 / 数据目录浏览 / 上传 / 提交并跟踪作业 / 看账户)。
- 价值:首个客户拿到可点的产品界面;证明"契约/服务可被真实图形客户端端到端调通"。

## 范围
- **In**:
  - 登录跳转(经 BFF)· 应用外壳(**可折叠**侧栏 + 顶栏企业名 + 登出)· 我的账户/组织。
  - **数据集**(原型 image#8 风格列表):名称/描述/模态/标签/格式/样本数/大小/创建人/操作(详情)+ 搜索;**上传**收在本页弹窗(消费 Plan 7 三段契约,presigned 直传)。
  - **数据目录(Catalog Explorer · 两栏)**:左 Gravitino 目录树(metalake→catalog→schema→datasets,可折叠)+ 右详情(概览/详情 Tab、表清单、关于此 Schema)。消费 metadata 的 `catalogs/schemas/datasets`。
  - **数据管线**(作业列表 + 状态/轮询到终态)· **创建作业**(源=已上传原始数据集)。
  - **后端小补(契约先行)**:metadata `Dataset` 加 **`format` / `num_samples` / `size_bytes`** 3 字段(契约 + metadata-service 存返 + data-pipeline 注册时写入)——让数据集页显真值。
- **Out / 推迟(带理由)**:
  - **v2 功能,前端不做也不占位**(owner 决:从原型拿掉):**SQL 查询 / 另存为**(查询引擎)· **权限/策略 Tab**(Cerbos ACL,v2)· **数据探查助手(Genie 对话)**(⑯ Agent 平台,v2)· **跨用户组授权共享**(ACL,v2)。
  - 上传后端端点(已交付 Plan 7)· 模态/标签的**后端字段**(本轮前端列保留、值best-effort/占位,后端 vN+ 填)· 富分页/排序后端 · 移动端适配。

> **组织模型(反复确认,硬约束)**:平台→企业→**用户组**→用户。**用户组是权限维度,不是上传目的地**——上传不让用户选组,组由身份(`/auth/me` 的单一成员关系)自动带出;数据集页**不出现用户组列**。跨组授权共享 = v2 ACL。

## 用户场景 & 验收(可证伪)
- **场景 1 登录/外壳**:**AC-1** 未登录访问受保护视图 → 跳 `/auth/login`(经 BFF→KC→回应用),回来顶栏显示用户 + 企业名。**AC-2** 登出 → 会话清、回登录态;旧会话再访问 → 跳登录。**AC-2b** 侧栏可折叠(收成图标)。
- **场景 2 数据集**:**AC-3** 已登录打开"数据集" → 看到**有权访问**的数据集列表(image#8 字段;format/样本数/大小 显真值);搜索可筛;点"详情"看单集。
- **场景 3 上传(消费 Plan 7)**:**AC-4** 在"数据集"页点"上传数据集" → 填名 + 选文件(**不选组**)→ 走三段(请求上传→presigned 直传 OSS→complete)→ 成功后出现在列表;**AC-5** 大文件分片显进度、失败可重试、presigned 过期可重取;越权由后端 403、前端友好提示。
- **场景 4 数据目录(Catalog)**:**AC-6** 打开"数据目录" → 左树展开 metalake/catalog/schema、可折叠;选 schema → 右详情列出该 schema 下数据集(名/owner/格式/注册时间/共享)+ 概览;**只见有权访问的**(can() 过滤)。
- **场景 5 作业**:**AC-7** "创建作业"提交(源=已上传原始集)→ 202、入"数据管线";**AC-8** 运行中作业自动轮询到**终态**(按 `terminal`),终态展示产物/错误。
- **场景 6 账户**:**AC-9** "我的账户"显示 user、企业(名,隐藏标识)、所属用户组、角色(来自 `/v1/me/orgs`)。
- **边界/异常**:会话过期(401)→ 跳登录;变更请求 CSRF 前端自动带;跨组/无权数据 → 列表不出现(后端过滤);后端 503/网络错 → 友好提示不白屏。

## 功能需求(可测)
- **FR-001** 前端 MUST 经 **gateway/BFF 同源**调 API;MUST NOT 直连下游、MUST NOT 自行向 Keycloak 换 token。**例外(ADR-020 §5):仅上传字节直 PUT 到 OSS**(非同源);控制面仍同源。
- **FR-002** 未认证访问受保护视图 MUST 跳 `/auth/login`(或 401 拦截后跳)。
- **FR-003** 变更请求 MUST 带 `X-CSRF-Token`。
- **FR-004** 列表/详情 MUST 只展示后端 `can()` 返回的数据;前端 MUST NOT 自做授权判定。
- **FR-005** 作业 MUST 能轮询到终态(按 `terminal`,非状态串匹配)。
- **FR-006** MUST NOT 在前端存储/暴露 access/refresh token。
- **FR-007** 上传 MUST 走 Plan 7 三段契约;**MUST NOT 让用户选目标组**(组由身份带出)、MUST NOT 自拼 OSS key;隔离/审计由 Plan 7 后端保证。
- **FR-008** 上传 MUST 显示进度、失败可重试、presigned 过期可重取;产物(`ready`)MUST 可在"创建作业"选为源。
- **FR-009** 数据集页 MUST 显示 `format/num_samples/size_bytes`(来自 metadata 新字段);后端缺值时 MUST 优雅占位(不报错)。
- **FR-010** v2 功能(SQL/另存为/权限策略/Genie 助手)MUST NOT 出现在本轮 UI。

## 关键实体(概念级)
- **Me**:当前用户 + 组织(user、企业(隐藏标识,显示名)、用户组、角色、csrf)。
- **Dataset**:数据集(名/描述/owner/scope/位置/创建 + **format/num_samples/size_bytes** 新增;模态/标签 best-effort)。
- **Catalog/Schema**:Gravitino 层级(metalake=企业、catalog=数据源、schema=数据域)——目录树/详情。
- **Job** / **PrepareJobRequest**:作业及创建输入(源=已上传原始集)。
- **RawDataset**:上传的原始数据(名/OSS raw 路径/大小/上传状态;Plan 7 契约)。

## 未决
- 无静默 TBD。Plan 7 契约已冻结;metadata 3 字段为本 plan 内契约任务(Task 1 冻结);前端工具链为 Task 探针(见 design DoR #4)。
