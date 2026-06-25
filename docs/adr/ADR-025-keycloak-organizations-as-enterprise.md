# ADR-025: 企业 = Keycloak Organization(不透明 id)+ 注册/邀请;v1 移除"用户组"层(group→Cerbos)

- 状态：**Accepted(2026-06-24,owner 拍板)**。宪法本体同步(§1.1/1.2/1.3/1.4/1.6/2.1/2.2/5.1/8 + CLAUDE.md)+ 代码实现**随 [KC-org plan](../superpowers/plans/2026-06-24-kc-organizations-enterprise/) 同批落地**(保持宪法 ≡ 实现现实);本 ADR 决策即生效,进 writing-plans 仍需过 DoR(④ KC 探针为 plan 首任务)。
- 决策人：owner
- 相关：**supersede [ADR-010](./ADR-010-multi-enterprise-tenancy-model.md)**(两级租户/资源归属模型)、**amend [ADR-016](./ADR-016-gravitino-tenancy-mapping.md)**(企业标识来源/值)、**沿用并衔接 [ADR-024](./ADR-024-owner-based-dataset-ownership.md)**(owner 授权;本 ADR 顺势移除 group 维度)、**修订 constitution** §1.1/1.2/1.3/1.4/1.6/2.1/2.2/5.1/8(见末尾同步草案)。
- 调研：[spike 2026-06-23 KC Organizations vs groups](../superpowers/spikes/2026-06-23-kc-organizations-vs-groups.md)(KC 26.6.2 实测;**注:spike 的"alias=e-XXXX 零迁移"前提已被本 ADR"不透明 id"决策取代**)。spec/design:[`2026-06-24-kc-organizations-enterprise/`](../superpowers/plans/2026-06-24-kc-organizations-enterprise/)。

---

## Context

现状"企业"是 **KC realm group 路径约定**(`/e-XXXX/g-YYYY/{admins,members}`),企业/访问组/角色全编码在 group 路径里,`parse_context` 用两条正则解析。这套有三个结构性问题:

1. **企业不是结构化实体**,只是路径前缀的文化约定 —— 无法挂"企业级"能力(邮箱域归属、邀请、per-org SSO)。直接后果:自助注册的用户落不到任何企业,一进业务就撞 403(实测 huo 账户)。
2. **owner 模型(ADR-024)落地后,"用户组(group)"在 v1 授权里已不起作用**:`can()` 只按 企业(硬隔离)+ owner 判,`group_id` 不参与决策。group 却仍硬塞在身份层级(四级 平台→企业→**用户组**→用户)与 KC group 树里,是**空壳结构**。
3. 宪法 §2.1 其实**早已声明 enterprise=Organizations**,但实现一直用 group 前缀代偿 —— 文档与实现长期不一致。

KC 26.6.2 的 Organizations(核心 GA 26.0)能干净表达"企业"一级实体,并自带 group 方案没有的:**邮箱域自动归属、邀请、identity-first、per-org IdP**。

## Decision

### 1. 企业 = Keycloak Organization,标识不透明

- 企业是 **KC Organization** 一级实体;**`enterprise_id` = org 的不透明标识(KC org id),不再人工编码 `e-XXXX`**(§1.4 不透明 ID 更彻底)。
- 企业归属来源 = token 的 **`organization` claim**(KC Organization Membership mapper);`parse_context` 改读此 claim(替代 group 路径正则)。
- **下游一致换值**:Gravitino metalake = `enterprise_id.replace("-","_")`(沿用现函数,**不加 `org_` 前缀**)、OSS 路径前缀、契约 `enterprise_id` pattern(放宽容不透明 id,4 处)、fileset 属性、审计字段。**v1 prod 无数据 → 清晰切换(非在线数据迁移);dev 数据可重建。**

### 2. v1 移除"用户组(group)"层 —— 身份降两级,group 维度整体清理

- 身份层级 **四级 → 两级:平台 → 企业 → 用户**。**取消"用户组(group)"这一身份层**。
- **`group_id` 维度全面清理**(owner 拍:不留 None 占位):删 `Membership.group_id` / `Resource.group_id` / `AuditEvent.group_id` / `role_in` 的 group 参数 / `/v1/me/orgs` 的 group_id / 契约 `^g-` pattern / `_caller_group` 及相关测试。
- 企业内**角色仅 `member` / `enterprise-admin`**(`group-admin` 随访问组层移除);角色用 **org 属性 / realm role 表达**,**不再经 group 子组路径编码**。
- **"按 group 授权资源"= Cerbos(v-next)**:未来对 OSS/数据集可按 **user(owner)或 group** 授权,届时 group 是 **Cerbos 的授权主体集合**(可由 KC group / Organization Groups / Cerbos 自管),**与身份层级解耦、用到再引入**。原 `group-admin` 的细粒度能力随 Cerbos 回归。

### 3. 注册 + 加入企业(企业管理员授予)

- 自助注册创建账号;**加入企业 = 企业管理员授予成员关系**(或邀请,prod SMTP 后)。注册后未归属企业的账号进入"待分配"显式状态(`enterprise_of` 缺企业 → 显式拒 + 可理解提示,不悬空)。
- 企业管理员可**邀请**用户加入(KC org 邀请);受邀者接受成成员;过期/撤销邀请被拒。

> **修订(2026-06-26,live 验收发现 + owner 拍 C 方案)**:原案"自助注册按邮箱域 identity-first 自动归属"**显式推迟 v-next**。实测发现 KC 26.6.2 的"按域自动归属"**只绑在 identity-first 登录流**(及 IdP 接入/邀请),而 owner 要"用户名+密码同页登录"必须**禁用 identity-first** —— 两者原生冲突;KC 注册流无 org 步(form-action providers 无 organization)。owner 决:**v1 加入企业由企业管理员处理(合理),不做自助注册自动归属**;域自动归属(需后端自建"邮箱域→入会+刷新 token",见 design 备选 A)留 v-next。realm 仍登记 org domains(供 v-next + 邀请校验),但 v1 不驱动自动入会。

### 4. 隔离不变式(保持)

- 企业仍是**硬隔离边界**(§1.6);`can()` 判定逻辑零改(`libs/authz/engine.py` 实测仅按 enterprise + owner 判,不读 group_id)——**只换企业值来源、移除 group 维度**。
- 平台管理员仍只走 `/admin/*`;伪造 `organization` claim 与伪造 groups 同防线(BFF 加密会话内 access token,剥离客户端鉴权输入)。
- **多-org claim 二义** → `enterprise_of` 沿用"0/多企业显式拒",不静默挑一个。

### 5. 否决项

- **锁 org alias = `e-XXXX`(零数据迁移)**:否决。owner 取 §1.4 更彻底的不透明 id;v1 无 prod 数据,迁移成本可接受。
- **混合保留 realm group 作访问组**:否决。owner 模型后 group 在 v1 不参与授权,保留即空壳;改由 Cerbos 在需要时引入。
- **Organization Groups(26.6 原生访问组)即上**:否决(v1)。新特性坑未知;v1 不需要任何访问组结构。
- **KC realm role 编码访问组 / 保留 `group_id` None 占位**:否决。前者角色爆炸;后者留漂移口,owner 选一次清理干净。

## Consequences

**正面**:企业成结构化实体 → 注册自动归属/邀请/per-org SSO 有处可挂(修掉无企业 403);身份模型最简(两级 + owner);文档与实现对齐(§2.1 早已声明 Organizations)。
**负面/代价(接受)**:enterprise_id 不透明化 = 跨契约/Gravitino/OSS/审计一致改值 + parse_context/契约/测试机械改(承重墙,design 列具名清单);依赖 KC 26.6.2 Organizations 行为(token claim 形态/多-org 坑 → 探针优先实测钉死);宪法多条同步修订。
**升级路径**:per-org IdP、Organization Groups(原生访问组)、多企业用户、Cerbos 的 group 授权维度 —— 均 v-next,本 ADR 的两级 + 不透明 id 是其地基。

## 外部依赖事实(探查优先,实测前不写死)

KC 26.6.2 的 `organization` claim 真形态 / 是否进 access token / 多-org 行为 / 注册自动归属流 / 邀请 API —— **作 plan 首任务探针实测**(spike 记了预期形态 + 5 个已知坑);**决策门 if/then** 见 design。本 ADR 的命名/解析规则待探针确认 org id 真字符集后定案。

---

## 宪法同步草案(本 ADR Accepted 后,与实现同批施行;§0 硬纪律)

> 以下为 `docs/constitution.md` 的逐条 before→after 草案,owner 拍板 ADR 后施行(改宪法本体 + CLAUDE.md 引用)。

- **§1.1 层级**:`平台 → 企业 → 用户组(group) → 用户`(四级)→ **`平台 → 企业 → 用户`(两级;取消"用户组"身份层)**。
- **§1.2 类型**:`EnterpriseId / GroupId 是独立类型` → **删 `GroupId`;仅 `EnterpriseId`**。
- **§1.3 标识**:`enterprise_id=e-XXXX、group_id=g-XXXX` → **`enterprise_id = 不透明 org id`;删 `group_id`**。
- **§1.4 资源命名**:`必须含 enterprise_id(私有资源还须 group_id)` → **`必须含 enterprise_id`(删"还须 group_id");`display_name` 仍严禁进资源名/路径/schema/label**。
- **§1.6 硬隔离不变式**:`非 admin 路径必须 enterprise_id 匹配;私有资源还须 group_id 匹配或 enterprise-admin` → **`必须 enterprise_id 匹配;私有资源按 owner(owner==ctx.user 或 enterprise-admin),删 group_id 匹配`(衔接 ADR-024)**。
- **§2.1 身份**:`单一 realm + Organizations(企业)+ Group 子组(用户组+角色)` → **`单一 realm + Organizations(企业,不透明 id)+ 注册邮箱域归属/邀请;删 Group 子组(无用户组层)`**。
- **§2.2 角色**:`角色经 Group 子组路径编码(/e-x/g-y/{admins|members}),随 groups claim` → **`角色 = member / enterprise-admin,经 org 属性 / realm role 表达,随 organization claim;不再用 group 子组路径编码`**。
- **§5.1 可观测**:`统一携带 enterprise_id / group_id label` → **`统一携带 enterprise_id label`(删 group_id)**。
- **§8 CI grep**:`无散落 enterprise_id / group_id 直接比较` → **`无散落 enterprise_id 直接比较`(group_id 已删)**;ci_guards 相应调整。
- **CLAUDE.md**:架构宪法引言里"多企业租户与标识"指针随之更新(企业=Organization 不透明 id、两级、group→Cerbos)。
