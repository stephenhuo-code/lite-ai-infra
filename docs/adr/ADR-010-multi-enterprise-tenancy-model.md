# ADR-010: 多企业 SaaS 租户模型 — 单 Realm + Keycloak Organizations（身份/组织/角色全在 Keycloak）

- 状态：Accepted
- 日期：2026-06-04
- 决策人：平台团队（P1/P2/P3）
- 相关：**修订 ADR-002**（单 realm 多 group → 单 realm + Organizations）/ design §0 核心架构原则 / design §3.2 租户模型 / **ADR-011**（Cerbos 授权）/ ADR-005（日志栈，审计索引）

---

## Context

### 需求变化

v1 定位从"公司内部单租户平台"升级为 **对外多公司 SaaS**。层级四级：

```
平台 → 企业(客户) → 用户组 → 用户
```

约束（经多轮澄清确认）：

1. **企业 = 计费 / 合规 / 隔离硬边界**；企业之间默认强隔离。
2. **资源归属：企业共享 + 用户组私有**（两级）。
3. **v1 不需要跨企业同一身份**（一个用户只属一个企业）；但模型不排斥未来扩展。
4. **统一登录**；各企业自带 SSO 是未来需求（v1 不强制）。

### 关键技术事实

- Keycloak 是隔离用户库 + "先选 realm 再验密码"；realm 内 email 唯一。
- realm-per-企业 会把"同一个人"在不同企业劈成无关账号、无法统一登录——但 v1 既不需要跨企业身份，realm-per-企业 仍可行；不过它有 N realm 运维成本 + Keycloak 不擅长上千 realm + 新企业要 provision realm 等缺点。
- Keycloak **Organizations**（GA 26.0）支持单 realm 内多组织 + per-组织 IdP/域名登录路由 + 一人可属多组织。
- Keycloak **Group** 支持嵌套子组；**子组路径可编码"组+角色"并随 token 的 `groups` claim 带出**，从而无歧义表达"在哪个企业/组、什么角色"。

---

## Decision

### 1. 身份拓扑：单一 Realm + Organizations（模型 B）

- 单一业务 realm；**企业 = Keycloak Organization**（承载 SSO / 域名 / 登录路由）。
- realm-per-企业 **不采用**，仅作"未来强合规大客户要求独立用户库"的例外。
- 定位类比：单 realm ≈ AWS Identity Center / 阿里云云 SSO（统一身份层）；企业 ≈ Account 的"资源/计费边界"面孔。

### 2. 组织 / 成员 / 角色：全部在 Keycloak（不建 PG）

| 概念 | Keycloak |
|---|---|
| 企业 | **Organization** |
| 用户组 | **Group（user group）**，按层级建 |
| 用户 | **User** |
| 成员关系 | Group 成员 |
| **角色** | **用子组编码**：`/e-{eid}/g-{gid}/admins`、`.../members` |

**角色挂在子组上、随 token 的 `groups` claim 带出**：

```
组结构:      /e-0001/g-0001/admins
            /e-0001/g-0002/members
token groups: ["/e-0001/g-0001/admins", "/e-0001/g-0002/members"]
解析:        (企业 e-0001, 组 g-0001, 角色 admin) + (e-0001, g-0002, member)
```

子组路径**无歧义**地携带"企业+组+角色"，应用直接解析 token 判权——**不需要 PG 存成员/角色**。

### 3. 授权：Cerbos（详见 ADR-011）

- **PDP = Cerbos**（无状态，策略 in git）。
- **principal ← 从 token 的 `groups` claim 解析**（不查 PG）。
- **resource 属性 ← 从资源自身读**（见 §4），不依赖中央元数据库。
- `PolicyEngine.can(ctx, action, resource)` 仍是唯一出入口。

### 4. 资源归属"编码在资源自身"（v1 无中央元数据 PG）

Cerbos 判权所需的 `enterprise_id/group_id/scope` 从资源本身读：

| 资源 | 归属编码 |
|---|---|
| OSS 对象 | 路径前缀 `oss://.../e-0001/g-0001/...` |
| 训练/推理 K8s 负载 | label `enterprise_id` / `group_id` |
| MLflow run | tag `enterprise_id` |
| Gravitino 资产 | schema 名 `e_0001_g_0001` |

### 5. 审计：v1 必做，只追加，不入 PG

- **系统记录**：Platform API 在每次 mutation / `/admin/*` / 拒绝时，**只追加写 OSS**（`oss://audit/{yyyy}/{mm}/{dd}/*.jsonl`）。
- **查询**（可选）：OpenSearch 起来后 Fluent Bit 索引到 `audit-*`（沿用 ADR-005 / §3.11）。
- **决策审计**：Cerbos 自带 decision log。
- **字段**：actor / action / resource(kind+id+enterprise/group) / decision / ts / ip / request_id。
- ⚠️ **降级**：无 PG = 审计为**事后尽力写**，非"与业务同事务原子写"（强保证待 PG 回归）。

### 6. v1 推迟（需要时再引入 PG）

- **两级预算 / 配额账本**（事务记账）——v1 无花费限额（Kueue 静态配额可顶）。
- **中央资源元数据目录 / 跨企业聚合查询**。
- **同事务原子审计**。

可逆性：`can()` 唯一出入口 + **resource 属性来源做成抽象**（v1 从 label/tag/路径读，将来从 PG 读），加 PG 时 handler 不改。

### 7. 标识符 + 版本

- `enterprise_id`: `e-XXXX`（全局唯一）；`group_id`: `g-XXXX`（企业内唯一）；`display_name` 绝不进资源名。
- **Keycloak 升级到 26.6.2**（Organizations 成熟 + `--import-realm` 相关修复；移除 26.1 禁用 organization 的 workaround）。

---

## Consequences

### 正面
- **v1 架构极简：Keycloak（身份/组织/角色）+ Cerbos（授权）+ OSS 审计，无 PG。**
- 统一登录 + per-企业 SSO（Organizations 原生）。
- 授权 principal 全部来自 token，无 PG 往返。

### 负面 / 代价（接受）
- **Token 有 TTL**：改角色（改子组）要等 token 刷新才生效（短 TTL 缓解）。
- **子组数 = 用户组数 × 角色数**：规模大时 Keycloak 组数膨胀，需关注。
- **v1 无预算限额**、**无中央资源目录/聚合查询**、**审计为尽力写**（非原子）。
- PG 里若将来存资源行，其 `enterprise_id/group_id` 是来自 Keycloak 的不透明 id，无跨系统外键。

### 风险登记

| 风险 | 缓解 |
|---|---|
| Token stale 导致权限滞后 | 短 token TTL；高敏操作可强制 re-auth |
| 子组膨胀 | 监控组数；规模上来评估 Organization Groups 或 PG |
| 审计非原子（漏记）| 尽力写 + 关键路径双写；PG 回归后改同事务 |
| 强合规客户要独立用户库 | 例外开独立 realm |

---

## 附录 A：硬纪律（取代 design §3.2 旧 6 条，写进 constitution）

1. **`EnterpriseId` / `GroupId` 是独立类型**；资源标识构造函数只接收对应类型。
2. **资源命名必须含 `enterprise_id`**（私有资源还须 `group_id`）；`display_name` 严禁进资源名/路径/schema/index/label。
3. **JWT 仅作认证 + 携带组路径**；`(企业,组,角色)` 由 token 的 `groups` claim 解析；handler 不从 query/body 读 `enterprise_id`/`group_id`。
4. **每次访问决策必须经过 `PolicyEngine.can(ctx, action, resource)`**（内部调 Cerbos，ADR-011）；禁止散落 `if enterprise_id == ...`。
5. **硬隔离不变式**：非 admin 路径必须 `resource.enterprise_id == ctx.enterprise_id`；私有资源还须 `group_id` 匹配或 `enterprise-admin`；跨企业仅 `platform-admin` 走特权 API。
6. **资源归属编码在资源自身**（OSS 路径 / K8s label / MLflow tag / Gravitino schema），Cerbos 的 resource 属性据此读取。
7. **CI 防线**：import-linter 依赖方向 + grep `display_name` 泄漏 + grep 散落 `enterprise_id/group_id` 比较。

## 附录 B：为什么 v1 选模型 B 而非 realm-per-企业

即使 v1 不跨企业，模型 B 仍更优：新企业开通 = 建 Organization + 组，不 provision realm；单 realm 扛海量企业；Organizations 已提供 per-企业 SSO + 隔离；且免费保留未来跨企业的演进口子。realm-per-企业 仅当"用户库必须物理分库"的强合规需求出现时作例外。
