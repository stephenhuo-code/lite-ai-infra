# 调研:用 Keycloak Organizations 作"企业" vs 现状 group+subgroup

> 状态:**调研/决策输入**(非 ADR)。owner 拍板后,若采纳 → 写 ADR(supersede/amend ADR-010 + ADR-016)再开发。
> 日期:2026-06-23。KC 版本(实测):**26.6.2**(`deploy/dev/docker-compose.yml:16`)。

## 结论先行
- **可行且更好**:KC Organizations 能干净替代现状用 group 路径硬编码的"企业"维度,且自带 group 方案完全没有的能力:**邮箱域自动归属、企业级 SSO(per-org IdP)、邀请、identity-first 登录**——这正好解决你之前问的"注册 + 用户自动落到企业"。
- **关键利好**:我们在 **26.6.2**,**Organization Groups(企业内层级组,26.6 新增)可用** → "企业内的访问组/数据域"(现状 `g-XXXX`)也能**原生**表达(org 间路径隔离,比手工 `/e-XXXX/g-XXXX` 更干净),**不必被迫保留 realm group**。
- **改造半径:中等偏小**——若**保持 ID 值不变**(org `alias=e-XXXX`、org-group 路径=`g-XXXX`),则 Gravitino(metalake `e_XXXX`)、OSS 路径(`e-XXXX/g-YYYY`)、契约 pattern、fileset properties、`can()`、各业务端点**全透明零改**;改动集中在 **token claim 映射 + `parse_context` + realm 配置 + 测试**。估 **8–15 人日**(取决于是否上 org-groups + 迁移脚本)。
- **代价/风险**:token claim 形态变(`groups` 扁平路径 → `organization` 以 alias 为 key 的对象)、多-org claim 的已知坑要驯服、Organization Groups 是新特性、需 supersede ADR-010/016、需迁移脚本。
- **建议**:**采纳 Organizations 作企业**;访问组维度**先用混合(org=企业 + 保留 realm group=访问组)落地、Organization Groups 作为紧随其后的升级**(降低"新特性"风险),或直接上 org-groups(更干净,需多验证)。**先关掉在途的 8b(登出已修),这是独立的地基 sprint。**

---

## 现状模型(被对比方)
- 企业 = KC group `/e-XXXX`(+ `/e-XXXX/admins`);访问组/数据域 = 子组 `/e-XXXX/g-XXXX/{members,admins}`;平台管理员 = `/platform-admins`。
- token 带 `groups` 全路径声明 → `libs/identity/context.py:parse_context` 用两条正则解析出 `(enterprise_id, group_id, role)` + `is_platform_admin`。
- 下游:`enterprise_of` / `can()`(libs/authz)按三元组判隔离;Gravitino metalake=`e_XXXX`(ADR-016);OSS 路径 `e-XXXX/g-YYYY/...`;**group 是访问属性(写在 fileset properties),不是 namespace**(ADR-016 的核心决定)。
- 钉死它的 ADR:**ADR-010**(两级租户模型)、**ADR-011**(can() 授权)、**ADR-016**(Gravitino 映射)。

## KC Organizations 能力(KC 26)
| 能力 | 说明 | 对我们的价值 |
|---|---|---|
| Organization 实体 | realm 内一级实体:`name/alias/domains/attributes/redirectUrl/enabled/id` + 绑定 IdP | `alias` 当稳定企业标识(可设 = `e-XXXX`) |
| 成员 managed/unmanaged | managed=org 为账号唯一真相源(删 org 删账号);unmanaged=已有 realm 用户挂进来(移出仅解关系) | **迁移要点**:已有用户以 **unmanaged** 加入,保账号 |
| 多 org | 一个用户可属多 org,但**最多一个 managed** | v1 单企业够用;多企业用户走 unmanaged |
| token claim `organization` | 内置 `organization` client scope + Organization Membership mapper;claim 以 **alias 为 key 的对象**;org id/attributes **需在 mapper 勾选**才带 | parse_context 改读此 claim |
| **域 domains + identity-first** | 按邮箱域匹配 org → 自动归属 + 切到该企业流程 | **解决"注册/登录自动落企业"**(group 方案没有) |
| per-org IdP | 每企业绑自己的 SSO | B2B 真需求(v2 价值大) |
| 邀请 invitation | org 级邀请链接 API | 受控上线(对齐"邀请制") |
| **Organization Groups(26.6)** | org **内**层级 group(`/Engineering/Backend`),**org 间路径隔离**;mapper 把 `organization.<alias>.groups:["/path"]` 进 token | **原生表达 `g-XXXX` 访问组**,比现状更干净;**我们 26.6.2 可用** |
| Admin REST | `/admin/realms/{realm}/organizations`(增删改查/成员/邀请/IdP);`/users/{id}/organizations` 反查 | 迁移脚本 + 管理用 |

## 关键分水岭:访问组(g-XXXX)怎么放
| 选项 | 做法 | 优 | 劣 |
|---|---|---|---|
| **混合(保守,推荐起步)** | 企业=Organization;访问组=**仍用 realm group**(`/g-XXXX` 或现状路径)+ role | 改动最小;org-groups 新特性风险不沾;兼容任何 26.x | KC 里两套树并存(org + group),维护略多 |
| **全 org-groups(更干净)** | 企业=Organization;访问组=**Organization Groups**(org 内 `/g-XXXX`)+ org-group membership mapper | 单一身份模型;org 间路径隔离;语义最正 | org-groups 是 26.6 新特性,坑未知;token 多-org 行为要驯服 |
| 用 KC role 表达访问组 | role 编码 `group:g-XXXX:member` | 不需子组 | 角色爆炸(企业×组×角色),管理差 —— 不推荐 |

> 无论哪种,**"角色"(member/group-admin/enterprise-admin)建议继续用路径后缀或 KC role 表达,不塞进 org 本身**。

## 改造半径(以"ID 值不变"为前提 → 下游透明)
| 层 | 改动 | 性质 | 风险 |
|---|---|---|---|
| Realm 配置(`realm-lite-ai.json` + 在线) | 建 org(alias=e-XXXX)+ 成员 + `organization`(及 org-groups)mapper;保留/调整 group 树 | 结构改 | 中(需重新 provision + 真机验证 token) |
| `libs/identity/context.py:parse_context` | 解析新 `organization` claim(+ org-groups)→ 仍产出 `(enterprise_id, group_id, role)` 三元组 | 机械改(签名不变) | 低 |
| `_scaffold/auth.py` / `bff/middleware.py` | 透传 claims 给 parse_context;**几乎不改**(只要 mapper 把 org 放进 access token) | ~零 | 低 |
| `libs/authz`(can/role_in)、业务端点(identity/metadata/data-pipeline) | **零改**(seam:只要 memberships 三元组不变) | 零 | 极低 |
| Gravitino 映射(`_metalake=e_XXXX`)、OSS 路径(`e-XXXX/g-YYYY`)、契约 pattern、fileset properties | **零改**(alias=e-XXXX、org-group=g-XXXX,值不变) | 零 | 极低 |
| `/v1/me/orgs` 契约/实现 | 可选新增 `organization` 字段(保留旧三元组兼容) | 小 | 中(契约演进) |
| 测试(identity/authz/services/integration ~7 文件) | 改"造 token"的 claim 形态(groups → organization);**断言/逻辑不变** | 数据改 | 低(量大但机械) |
| ADR | 新 ADR supersede/amend ADR-010 + ADR-016 | 决策 | 高(owner 拍板,前置) |

**估算**:核心(org+混合 group + parse_context + 测试 + realm)≈ **8–12 人日**;上 org-groups + 迁移脚本 + 真机/阿里云验证 → **12–15 人日**。

## 迁移(已有用户/数据)
- 建 org **alias=e-0001**(与现 `e-XXXX` 同值)→ enterprise_id 不变 → **OSS/Gravitino/契约零迁移**。
- 已有用户(alice 等)以 **unmanaged member** 加入对应 org(保账号)。
- `g-XXXX`:混合方案保留现 group;org-groups 方案在 org 内建 `/g-XXXX` 并迁成员。
- huo(无企业)→ 这套下可由"邮箱域归属/邀请"自然纳入某 org(正是你要的)。
- 无官方一键迁移工具 → 写脚本:解析现 group 路径 → 建 org/org-group → 加成员;token mapper 切换后下游 parse_context 同步改。

## 已知坑(规划必须固化)
1. **多-org token claim 会"消失"**:不带 scope 选择器时历史回归 bug(#39402/#43635)→ 必须用 `scope=organization:*` 或 identity-first 选定单 org;在 client scope 配置里固化 + 验收。
2. **org claim 默认不进 access token** → mapper 勾 "Add to access token"(社区常踩)。
3. **managed 误成 unmanaged** 的实现 bug(#43094)→ 建 managed 成员后验证实际类型。
4. **一个用户仅一个 managed membership** → 跨企业用户建模注意(其余 unmanaged)。
5. **Organization Groups 是 26.6 新特性** → 上之前在非生产验证多-org + group claim 的 token 输出。

## 优劣对比(一页)
| 维度 | 现状 group+subgroup | 改 Organizations |
|---|---|---|
| 企业隔离 | 文化约定(路径前缀 `/e-XXXX`) | **结构化原生**(org 实体) |
| 访问组(数据域) | 子组 `/e-XXXX/g-XXXX`(成熟、已测) | org-groups(26.6,更干净但新)/ 或混合保留 group |
| 注册→自动归企业 | **无**(自助注册成无租户用户,撞 403) | **有**(邮箱域归属 + 邀请) |
| 企业级 SSO | 无 | **per-org IdP** |
| 现有代码兼容 | — | can()/Gravitino/端点透明;改 parse_context+token+realm |
| 数据迁移 | — | alias=e-XXXX 则**零数据迁移** |
| 成熟度/风险 | 现成、低风险 | org 核心 GA(26.0);org-groups 新(26.6) |
| 改造成本 | 0 | 8–15 人日 + ADR |

## 推荐 + 决策项(给 owner)
**推荐**:采纳 **Organization=企业(alias=e-XXXX,ID 值不变)**;访问组**先混合(保留 realm group)落地,org-groups 作紧随升级**;角色用路径后缀/role。这样:解决注册/自动归属 + 拿到 per-org SSO 增量,同时把下游改动压到最小、数据零迁移、风险可控。

**待 owner 拍的点**:
1. 是否采纳 Organizations 作企业?(总闸)
2. 访问组:**混合(保留 group,稳)** vs **org-groups(干净,新)**?
3. 是否锁 `alias=e-XXXX` / org-group=`g-XXXX` 以零数据迁移?(推荐是)
4. 时序:**先关 8b(登出已修)再起这个地基 sprint** vs 现在插队?

拍板后:写 ADR(supersede ADR-010/016)→ writing-specs(spec/design + DoR,含 KC 探针验证 token 形态/多-org/坑)→ plan → 执行。
