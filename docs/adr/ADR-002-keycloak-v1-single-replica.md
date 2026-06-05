# ADR-002: Keycloak 部署形态（v1 起 HA 双副本）+ 单 Realm

> 文件名 `...single-replica...` 为历史 slug；部署形态已于 2026-06-06 改为 **HA 双副本**（见下），保留文件名以稳定既有链接。

- 状态：Accepted（两次修订：① 2026-06-04 身份拓扑被 [ADR-010](./ADR-010-multi-enterprise-tenancy-model.md) 改为 单 realm + Keycloak **Organizations**、升 26.6.2；② **2026-06-06 部署形态由单副本升级为 HA 双副本**——转对外多企业 SaaS 后 Keycloak 是付费客户登录的关键路径，原"单副本"论证不再成立）
- 日期：2026-05-10
- 决策人：X-user team（P1/P2/P3）
- 相关：design doc §0 / §1.2（⑩ Keycloak）/ §3 选型表 / §6.1 P0 风险 / ADR-001（V8 推 v2）

## Context

Keycloak 是 v1 多租户身份基座，承担：

- OIDC IdP（Portal、SDK、CLI、Grafana、MLflow 等所有 client 的登录入口）
- 用户与组管理（用 group 表达租户归属）
- token 签发，Tenant Service 中间件解析 `tenant_id` claim 实现多租户隔离

> **2026-06-06 修订**：原决策为 v1 单副本（理由：内部单租户、HA 收益有限）。转为**对外多公司 SaaS**（ADR-010）后，Keycloak 成为**付费客户登录的关键路径**——任一时刻宕机即所有客户无法登录，直接影响商业 SLA。故 **v1 起即上 HA**。

HA 决策依据：

- 多企业 SaaS：Keycloak 宕机 = 全体客户登录中断，不可接受
- 身份是所有服务（Portal/SDK/CLI/Grafana/MLflow/Workspace）的统一入口，单点风险面最大
- token TTL 内缓存只能缓解、不覆盖新登录 / 新 client；对外客户的体验与合规 SLA 要求更高可用性

## Decision

### v1 部署形态

- **Keycloak 26.6.2，StatefulSet ≥2 副本**（无状态化：realm/签发密钥在 DB、会话走 Infinispan 分布式缓存，副本间一致）
- 后端 DB：阿里云 RDS PG **主备高可用**（自动故障转移 + 每日快照）
- **故障恢复 RTO 目标：分钟级**（单副本 / 单 AZ 故障自动接管）
- **Sprint 5 杀副本演练**（验证第二副本接管 + 平台无中断，对应 design §6.1 O6）
- 跨 region 容灾：v2 评估

### realm 拓扑

- **单业务 realm**：`lite-ai`
  - 所有租户的用户装在同一个 realm
  - 用 **group** 表达租户归属：`/tenants/{tenant_id}`
  - JWT claim mapper：把 user 所属的 `tenants/*` group 映射成 token 里的 `tenant_id` claim
- **多 client**：每个调用 Keycloak 的服务一个 client
  - `portal`（confidential，Authorization Code Flow）
  - `sdk` / `cli`（public，Device Authorization Flow）
  - `grafana` / `mlflow` / `workspace`（confidential，OIDC ingress 鉴权）
- **`master` realm**：仅放平台管理员账号（用于救火 / realm 配置 apply），**不放任何业务用户**

### admin 账号纪律

- `master` realm 里的 admin 账号 = 平台超级管理员
  - 强密码 + MFA 强制
  - 不日常使用，仅用于 realm 配置 apply 和救火
  - 凭证锁在 1Password 团队保险柜（v2 上 Vault）
  - 纪律违规视为 P0 安全事件

### 配置管理

详见 ADR-003（Realm IaC，使用 keycloak-config-cli）。所有 realm 配置变更**必须通过 IaC 流水线**，禁止在 Admin Console 手工点。

## Consequence

### 正面

- **无单点故障**：HA 双副本 + RDS 主备，单副本 / 单 AZ 故障自动接管，满足对外 SaaS 可用性要求
- 单 realm + Organizations 表达企业是多企业 SaaS 主流；跨企业用户、per-企业 SSO 天然支持（ADR-010）
- 后期若有"完全独立用户库"的强合规客户，可在同一 Keycloak 加新 realm 作例外，主 realm 不受影响

### 负面

- HA 增加运维复杂度与成本：副本间一致性（Infinispan 分布式缓存 / token 签发密钥）+ RDS 主备 + 杀副本演练（Sprint 5 验证）
- 企业隔离 v1 起在**资源层 + 授权层**（ADR-010/011），非身份层物理隔离 → 强合规客户走独立 realm 例外

### 中性

- realm 配置变更仍走 IaC（ADR-003）；副本间配置由共享 DB 保证一致

## 附录 A：Realm 概念速查（团队入门）

> 这一节是为了让新成员（特别是没用过 Keycloak 的 P1/P2/P3）能快速建立心智模型。不影响决策，仅作参考。

### Realm 是什么

**Realm**（中文译"领域 / 安全域"，团队约定**保留英文 Realm**避免与 K8s namespace / network domain 混淆）是 Keycloak 最顶层的隔离单位。

一个 realm 内部有自己的：

- 用户（User）
- 组（Group）
- 角色（Role）
- 客户端（Client，即接入此 realm 的应用）
- 登录页 / 主题
- token 签发密钥
- 认证流程（密码 / MFA / SSO 等）

**不同 realm 之间用户完全不互通**——是硬隔离单位。

### 常见误解纠正

| 误解 | 实情 |
|---|---|
| "Realm 是 root 账户" | ❌ Realm 是隔离容器，不是用户。最接近"root"的是 master realm 的 admin 用户 |
| "一个 Keycloak 只能有一个 Realm" | ❌ 一个实例可以有 N 个 realm，master 是默认管理 realm |
| "用户在 realm A，能不能在 realm B 登录" | ❌ 不能。realm 间用户库物理隔离 |
| "Group 和 Role 哪个表达租户" | ✅ 我们用 **Group** 表达租户（`/tenants/{tenant_id}`），Role 用于功能权限（如 `admin` / `member`） |

### v1 部署的具体形态图

```
Keycloak 实例（StatefulSet 单副本，v1）
│
├── master realm             ← 仅放平台 admin 账号（P1/P2/P3 各一）
│   └── 用途：登录 Admin Console 跑 realm 配置 apply / 救火
│
└── lite-ai realm            ← 业务 realm（v1 单 realm）
    │
    ├── clients
    │   ├── portal           （confidential, redirect_uri = https://portal.lite-ai.local/*）
    │   ├── sdk              （public,        Device Authorization Flow）
    │   ├── cli              （public,        Device Authorization Flow）
    │   ├── grafana          （confidential, OIDC ingress）
    │   ├── mlflow           （confidential, OIDC ingress）
    │   └── workspace        （confidential, OIDC ingress）
    │
    ├── groups
    │   └── /tenants
    │       ├── /x-user      ← X-user team（tenant_id = t-0001）
    │       └── /t-0002      ← v1 测试租户，用于隔离验收
    │
    ├── users                ← 所有租户的用户都在这里
    │   ├── alice            （member of /tenants/x-user）
    │   ├── bob              （member of /tenants/x-user）
    │   └── ...
    │
    ├── roles                ← 业务功能权限
    │   ├── tenant-admin
    │   └── tenant-member
    │
    └── protocol mappers
        └── tenant_id mapper ← 从 group path 提取 tenant_id 注入 JWT claim
```

## 后续动作

- [ ] Sprint 0a 0a-3：dev 环境部署 Keycloak v1 单副本（owner: P2）
- [ ] Sprint 0a 0a-4：keycloak-config-cli PoC（owner: P2，详见 ADR-003）
- [ ] Sprint 0b：staging/prod realm 配置 + apply 流水线（owner: P2）
- [ ] Sprint 0a：admin 账号凭证入 1Password 团队保险柜，MFA 强制开启（owner: P2）
- [ ] v2：Keycloak HA（StatefulSet 多副本 + DB HA + 副本演练）
