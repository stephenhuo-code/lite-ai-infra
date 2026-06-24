# Design — Keycloak Organizations 作企业 + 注册/邀请自动归属

> HOW。需求见 [spec.md](./spec.md)。地基决策落**新 ADR(supersede [ADR-010](../../../adr/) 两级租户模型、amend [ADR-016](../../../adr/ADR-016-gravitino-tenancy-mapping.md) 租户映射;沿用 [ADR-024](../../../adr/ADR-024-owner-based-dataset-ownership.md) owner 授权)**。调研事实(KC 26.6.2 实测)见 [spike](../../spikes/2026-06-23-kc-organizations-vs-groups.md)——**注:spike 的"alias=e-XXXX 零迁移 / 下游零改"前提已被 owner 决策"全新不透明 id + 清理 group 维度"取代,改造半径以本 design 的具名清单为准**。**引用既有家、不复制**(契约 `contracts/openapi/`;身份 `libs/identity/`)。

## 架构与隔离

### 模型:企业=org(不透明 id),两级租户,无访问组层
```
KC Organization  ──(成员关系 + domains + 邀请)──►  企业(enterprise,硬隔离边界)
   id (不透明 UUID) = enterprise_id 下游唯一来源
   alias / name / domains[] / attributes
企业内角色  ──────────────────────────────────►  member / enterprise-admin
   (org 属性 / realm role 表达;**无访问组层、无 g-YYYY 子组**)
平台管理员 ────────────────────────────────────►  /platform-admins → 仅 /admin/*
```
- **企业来源唯一变更点 = token 的 `organization` claim**(KC 内置 Organization Membership mapper);角色来源 = org 属性 / realm role(design probe 定);平台管理员沿用 `/platform-admins`。
- **关键不变式(改造半径压制点)**:`can()` 的**判定逻辑零改**——`libs/authz/engine.py` 实测仅按 `enterprise_id` 命中 + owner/enterprise-admin 判,**不读 group_id**(line 11 注释明示);`enterprise_of`、Gravitino metalake、OSS 路径(已 owner 化、本就无 group 段)隔离判定不动。**企业值来源**从 group 路径前缀换成 org claim,**Membership 的 (enterprise, role) 语义不变**。
- **但"零改"仅限授权判定;签名/字段收窄触及一批具名落点(必须进 plan 任务,不可当零改)**——owner 决:**group 维度一并清理**(非留 None 占位):
  | 落点 | 改动 |
  |---|---|
  | `libs/identity/context.py` | `Membership` 去 `group_id`;`parse_context` 改读 `organization` claim + 角色(去两条 group 正则);`role_in(enterprise_id, group_id=None)` → `role_in(enterprise_id)` |
  | `role_in` 调用点 | `services/data_pipeline_service/app.py:30,60`、`pipelines/data_prep/runner.py:70` 去 group 实参 |
  | `services/data_pipeline_service/app.py:19-24` | `_caller_group()` **删除**(及其在审计 label 的使用) |
  | `services/identity_org_service/app.py:14` | `/v1/me/orgs` 投影去 `group_id` |
  | `libs/authz/types.py` | `Resource.group_id` **删除** |
  | `libs/audit/oss_audit.py` | `AuditEvent.group_id` **删除**(§5.1 宪法审计 label 同步改) |
  | 契约 | `identity-org.yaml` Membership 删 `group_id`/`^g-` pattern;metadata/data-pipeline 无 group_id(已 owner 化)|
  | 测试 | `tests/identity/test_context.py`、`tests/services/data_pipeline/*`、authz 测试中 group 维度断言一并改 |
- **"按 group 授权资源"= Cerbos(v-next,解耦)**:未来对 OSS/数据集可按 user(owner)或 group 授权,group 是 **Cerbos 的授权主体集合**(用到再引入,可由 KC group/Organization Groups/Cerbos 自管),**不进 v1 身份层级**。

### 隔离不变式(保持)
- 企业硬隔离(§1.6):`can()` 仍先判 `enterprise_id` 命中(owner 模型 ADR-024 已是"企业边界先于 owner")。企业值来源从"group 路径前缀"换成"org claim",**判定逻辑不动**。
- 平台管理员(`/platform-admins`)仍只走 `/admin/*`(can() 现有闸)。
- 数据集归属=owner(ADR-024)不动;v1 移除访问组层,"按 group 授权"留 Cerbos。

## 数据模型 / 标识(不变量)

### enterprise_id 改为不透明(owner 拍:全新不透明 org ID)
| 项 | 现状 | 改为 | 不变量 |
|---|---|---|---|
| enterprise_id 值 | 人工编码 `e-XXXX` | **KC org `id`(不透明 UUID)** | §1.4 不透明;全局唯一;**界面绝不渲染** |
| Gravitino metalake | `e_XXXX`(= `eid.replace("-","_")`)| **沿用 `eid.replace("-","_")`**(owner 决:不加 `org_` 前缀)。org id 若标准 UUID(`[0-9a-f-]`)则 replace 后已合法 `[a-z0-9_]` | 确定性单向映射(非可逆);**待探针确认 org id 真字符集**——若含其他字符再补 sanitization |
| OSS 路径前缀 | `e-XXXX/{user}/…` | **`<org-uuid>/{user}/…`** | 仍 owner 路径(ADR-024),仅企业段换值 |
| 契约 pattern | `^e-[0-9a-z]+$`(identity-org/metadata/data-pipeline 共 4 处)| **放宽为不透明 id pattern**(如 `^[0-9a-z-]{8,}$`,容 UUID)| `/v1/me/orgs` 的 `group_id`(`^g-` pattern)**删除**(无访问组层)|
| fileset `enterprise_id` 属性 / 审计字段 | `e-XXXX` | org-uuid | 一致切换,无残留旧编码 |

> **承重墙**:enterprise_id 不透明化 = 跨契约 + Gravitino + OSS + 审计的一致改值。**v1 prod 无数据 → 清晰切换**(改 pattern + parse_context 产出 org-uuid + 重新 bootstrap);**dev 数据(coco/coco-1)可重建**,不做在线数据迁移。v1 **移除访问组层 / `g-YYYY` 子组**(group→Cerbos,与身份解耦)。

### token claim 形态(探查优先,实测钉死)
- 预期(spike,KC docs):`organization` claim 是**以 alias 为 key 的对象**;org `id`/attributes **需 mapper 勾选**才进;**默认不进 access token** → 必须勾 "Add to access token"。
- **probe(Plan 首任务)**:起真 KC 26.6.2 + 建 org + 配 mapper → 抓**真实 access token 的 `organization` claim 原文**(单 org / 多 org / 含 attributes / org id 字符集),记 `spikes/` 事实文档。
- **决策门(if/then,探针结果机械触发,无需二次拍板)**:
  - **若** 单 org 的 access token 稳定带"以 alias 为 key 的对象"且含 org id → **then** 固化 client scope(默认 `organization` mapper,Add-to-access-token 勾选),parse_context 直接读该对象。
  - **若** 多 org 下 claim 复现"消失"(已知坑 #39402/#43635)→ **then** 强制 **identity-first 单 org 选择** + client scope `organization:*`,parse_context 只认选定 org;**多-org 二义** → `enterprise_of` 沿用"0/多企业显式拒"(不静默挑一个)。
  - **若** org id 非标准 UUID 字符集 → **then** 补 metalake/路径 sanitization(见数据模型表);否则沿用 `replace("-","_")`。
- parse_context 新签名(seam 内):入参从 `groups: list[str]` 改为 **`organization`(dict)+(角色来源:org 属性/realm role)**;`Membership` 去 `group_id`;**返回类型 `Context` 形态收窄(去 group_id)**。`_scaffold/auth.py` / `bff/middleware.py` 透传该 claim。

### 状态机 / 实体
- **企业(org)**:`enabled`;成员 `managed`(org 为账号真相源,删 org 删账号)/ `unmanaged`(已有 realm 用户挂入,移出仅解关系)。**迁移用 unmanaged 保账号**;新注册落 managed?→ **probe 确认**(已知坑 #43094:managed 可能误成 unmanaged,建后验证实际类型)。
- **邀请**:`pending → accepted | expired | revoked`。
- **域归属规则**:org.domains[] → 注册时邮箱域匹配。**域冲突**(两 org 同域):建 org 时校验**拒绝重复登记同域**。

## 关键流程

### 1. 登录(企业从 org claim 解析)
KC 登录 → token 带 `organization`(+ 角色 claim)→ BFF 会话 → 业务请求注入 bearer → 服务 `context_from_request` → `parse_context(sub, organization, …)` → `Membership(enterprise_id, role)` → `can()`/隔离照旧(企业边界 + owner)。

### 2. 自助注册 + 邮箱域自动归企业(US3)
KC realm 开自助注册 + **identity-first**:输入邮箱 → 按域匹配 org → 注册完成**自动成 org 成员**(KC Organization domains 能力)。**无匹配域**:KC 行为 + 我方策略 = 注册置"待分配"(无企业成员关系)→ 业务侧 `enterprise_of` 缺企业时**显式 403 + 可理解提示**(现状已 default-deny,补提示文案),**不悬空**。具体 KC 自动归属是否需额外 authenticator/flow → **probe 确认**。

### 3. 邀请(US4)
企业管理员 → 经 BFF 调 KC org 邀请 API(`/admin/realms/{realm}/organizations/{id}/members/invite-*`)→ 受邀者接受 → 成 member。过期/撤销 → KC 拒。**对外契约**:BFF 新增"发起邀请/列邀请"端点(can() = enterprise-admin)。

### 4. 迁移/切换(US6,幂等脚本)
KC admin REST,**每步带幂等判据**:① 建 org(**by alias/name 查重**,存在则取用)+ 设 domains(by domain 查重);② 现有用户以 **unmanaged** 加入(**by user→org 反查**,已是成员则跳);③ 配 `organization` mapper + 角色表达(by mapper name 查重);④ **移除现有 `/e-XXXX/g-YYYY/` 子组结构**(by group path,存在才删;v1 无访问组层);⑤ Gravitino/OSS 在**新 org-uuid** 下 bootstrap(**by metalake name 查重**;**prod 无数据 → 是纯建非迁,dev 重建**)。**半态处理**:脚本记录"已切换"标记(或纯靠各步查重)→ 重跑安全、不留半态;**校验步**:跑完断言"旧 `e-XXXX` 路径无残留引用、新 org-uuid 下可读"。huo(无企业)→ 邮箱域归属或邀请纳入。

## 授权 / 安全 / 红线
- `can()`/owner 模型(ADR-024)**不改**;企业边界值来源换 org,判定不动。
- **威胁:伪造 org claim** → 与现有"伪造 groups"同防线:claim 来自 BFF 加密会话内 access token(JWKS 验签),客户端不可注入(`bff/proxy.py` 剥离客户端 `authorization`/`x-test-claims`)。
- **威胁:多-org claim 二义/消失** → 固化 client scope + identity-first 选单 org;parse_context 对二义**显式失败**(不静默挑一个,沿用 `enterprise_of` 0/多企业拒)。
- **越权邀请** → 邀请端点 can()=enterprise-admin;跨企业邀请拒。
- secrets:KC admin 凭据走 env/单一配置源(§5.2),不入仓;迁移脚本用 admin client 凭据按 dev/prod profile 注入。

## NFR
- **dev-prod parity(§5.3)**:realm 配置单一源(`deploy/dev/keycloak/realm-lite-ai.json` + 在线 provision 脚本);org/mapper/domains/注册流在 dev 与 prod **同套**(仅数据量/IdP 绑定不同)。
- **隔离**:企业硬隔离不变(上).
- **可观测**:企业归属、注册自动归属、邀请接受 写审计。
- **规模**:v1 单企业;parse_context O(claims) 解析,无新外部往返(org 在 token 内)。

## 依赖引用(既有家)
- 契约:`contracts/openapi/{identity-org,metadata,data-pipeline}.yaml`(enterprise_id pattern 4 处)+ BFF 邀请端点(gateway 内部,非 /v1)。
- 身份:`libs/identity/context.py`(parse_context seam)、`libs/identity/ids.py`(EnterpriseId)、`services/_scaffold/auth.py`、`services/gateway/bff/`。
- 决策:**新 ADR**(supersede ADR-010、amend ADR-016)+ owner 模型 ADR-024(沿用)。
- 事实:[spike](../../spikes/2026-06-23-kc-organizations-vs-groups.md)(能力 + 5 个已知坑)+ **本轮新增 KC 探针 RESULTS**(token claim 真形态/注册归属/邀请)。

## DoR 就绪门(逐项三态)
| # | 就绪项 | 状态 |
|---|---|---|
| 1 | 范围与出口 | **已决定**:企业=org(不透明 id)+ 注册/邀请;**v1 两级租户、无访问组层**(group→Cerbos);per-org SSO/org-groups/多企业 v-next(spec) |
| 2 | 接口契约 | **已决定 + 部分待定**:下游 enterprise_id pattern 放宽(4 契约);`/v1/me/orgs` **删 group_id**、加 organization + 企业 display_name;BFF 邀请端点(can=ent-admin)。第一个消费者=账户页/邀请 UI(低保真原型作 plan 早期任务) |
| 3 | 数据模型 | **已决定**:enterprise_id=org-uuid(§1.4)、metalake 沿用 `replace("-","_")`、OSS 前缀换值、**group_id 全面清理**(Resource/审计/契约/测试);org 成员 managed/unmanaged、邀请/域状态机;企业 display_name |
| 4 | 外部依赖事实 | **待探查(探针优先,Plan 首任务)**:KC 26.6.2 `organization` claim 真形态 + 多-org 行为 + access-token 携带 + 注册自动归属 + 邀请 API;**决策规则已写**(上) |
| 5 | 行为·边界·并发·威胁 | **已决定**:无匹配域显式处理、多-org 二义显式失败、伪造 claim 防线、迁移幂等、域冲突拒重复 |
| 6 | NFR | **已决定**:dev-prod parity(realm 单源)、隔离不变、secrets env、审计 |
| 7 | 验收与测试 | **已决定**:SC-001~007 + owner-readable runbook(建企业→注册/邀请→登录→全链路;**用真实会撞边界的数据**:跨企业越权、无匹配域注册、过期邀请,§3.4)+ 测试分层(parse_context 单元、authz seam、services、KC 集成)|
| 8 | 关键决策留痕 | **待落**:① 新 ADR(supersede ADR-010 / amend ADR-016;**记 owner 决策**:企业=org 不透明 id、v1 移除访问组层 + 清理 group_id、含注册/邀请;**否决方案**=锁 alias=e-XXXX 零迁移、混合保留 realm group、org-groups 即上、KC role 编码访问组、保留 group_id None 占位)。② **同步修订宪法本体**(§0 硬纪律):`docs/constitution.md` §1.1(四级→两级 平台/企业/用户)、§1.2/1.3(删 `GroupId`/`g-XXXX`)、§1.4/1.6(私有资源判定去 group_id)、§2.1/2.2(realm 去 g-子组;**角色经 org 属性/realm role 表达,不再路径编码**)、§5.1(审计 label 去 group_id)、§8(grep group_id 散落比较项)+ `CLAUDE.md` 引用。**与新 ADR 同批落地,owner 拍板前置** |

> **进 writing-plans 前必须**:① owner/独立评审过 DoR 8 项;② 落新 ADR(地基决策);③ KC 探针作 Plan 首任务(实测钉死 claim 形态再写后续机械任务)。
