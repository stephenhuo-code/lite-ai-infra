# ADR-002: Keycloak v1 单副本部署 + 单 Realm 多 Group 多 Client

- 状态：Accepted
- 日期：2026-05-10
- 决策人：X-user team（P1/P2/P3）
- 相关：design doc §0 / §1.2（⑩ Keycloak）/ §3 选型表 / §6.1 P0 风险 / ADR-001（V8 推 v2）

## Context

Keycloak 是 v1 多租户身份基座，承担：

- OIDC IdP（Portal、SDK、CLI、Grafana、MLflow 等所有 client 的登录入口）
- 用户与组管理（用 group 表达租户归属）
- token 签发，Tenant Service 中间件解析 `tenant_id` claim 实现多租户隔离

原 design doc 倾向"v1 即上 HA（StatefulSet 2 副本 + RDS HA）"。复盘后发现：

- v1 仅服务 X-user team 一个真实租户 + 一个测试租户，约十余用户
- HA 部署的代价（PG HA、副本演练、realm 配置同步漂移、故障转移演练）需要 P3 较多容量，但 v1 阶段产生的实际可用性收益有限
- P3 在原分工下已扛 7 个子系统，是 critical path 瓶颈
- 即使发生宕机，X-user team 通过本地缓存 token 在 token TTL 内仍可继续工作；最坏情况下重启 Keycloak Pod 的 RTO 可控制在小时级

## Decision

### v1 部署形态

- **Keycloak 24+，StatefulSet 单副本**
- 后端 DB：阿里云 RDS PG **单实例 + 每日快照**（不上 HA）
- **故障恢复 RTO 目标 = 4h**（v1 阶段可接受）
- 副本演练 / DB HA / 跨 AZ：**v2 再做**（参见 v2 Roadmap）

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

- P3 容量节省约 1-2 周（HA 部署 + 副本演练工作量推 v2）
- 降低运维复杂度，单 Pod 故障定位简单
- 单 realm + group 表达租户是行业主流（GitLab、Argo、Backstage 同样选择），跨租户用户（同一人属多租户）天然支持
- 后期若有"完全独立用户库"的强合规租户，v2 可在同一 Keycloak 加新 realm，主 realm 不受影响

### 负面

- **单点故障**：Keycloak 宕机期间所有新登录失败；已有 token 在 TTL 内仍可用 → 风险表 P0 已登记
- v1 多租户硬隔离是**软隔离**（group + claim mapper），管理员误操作可能跨租户授权 → realm IaC + code review 兜底，v2 评估是否拆 realm
- 后端 DB 单实例：RDS 实例宕机 = Keycloak 不可用，依赖阿里云 RDS SLA + 每日快照恢复

### 中性

- v2 升级到 HA 时需要：DB 改 HA、StatefulSet 加副本、realm 配置同步演练、token 签发密钥跨副本一致性验证 → 写进 v2 Roadmap

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

### Keycloak ↔ AWS 概念映射

| Keycloak 概念 | AWS 对应 | 说明 |
|---|---|---|
| **Keycloak 实例**（部署本身） | AWS 这个公司的整套 IAM 服务 | 一套软件 |
| **Realm** | **AWS Account**（不是 root user） | 独立的用户库 + 资源边界，跨 realm 不互通 |
| **多个 Realm 在同一 Keycloak** | **AWS Organization 下挂多个 Account** | 共享底层服务，彼此隔离 |
| **`master` realm 的 admin 用户** | **AWS Organization 管理账号 / root 账户** | 唯一能创建/删除其他 realm 的超级管理员；不日常使用 |
| **Client** | IAM 里的某个应用集成 / SaaS 集成入口 | Portal / SDK / CLI 各算一个 client |
| **User** | IAM User | 端用户或服务账号 |
| **Group** | IAM Group | 我们用它表达"租户归属" |
| **Role** | IAM Role | 权限单元 |
| **JWT** | STS 临时凭证 | 登录后拿到的 token，带 claims |
| **Realm 配置（IaC）** | CloudFormation / Terraform | 用 keycloak-config-cli 声明式管理（参见 ADR-003） |

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
