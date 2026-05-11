# ADR-007: 访问控制模型 — RBAC + 自研 ABAC PolicyEngine（v1），Cerbos（v2 候选）

- 状态：Accepted
- 日期：2026-05-10
- 决策人：X-user team（P1/P2/P3）
- 相关：design doc §3.2 多租户机制（资源全景 / 24 项资源 / 隔离矩阵 / 6 条硬纪律）/ ADR-002（Keycloak v1 单副本）

## Context

### 多租户访问控制需求

design doc §3.2 多租户机制硬纪律第 4 条要求：

> 每次访问决策必须经过 `PolicyEngine.can(ctx, action, resource)`，禁止散落 `if tenant_id == ...` 判断。

实际场景中典型授权决策：

| 决策场景 | 例子 | 用 RBAC 够吗 | 真正需要 |
|---|---|---|---|
| 用户能不能进这个租户 | alice 是不是 t-0001 成员 | ✅ | RBAC（看 group） |
| 能不能提交训练作业 | tenant-member 角色就行 | ✅ | RBAC |
| 能不能删某个作业 | 只能删自己的 / admin 全删 | ❌ | **ABAC**（owner 属性） |
| 能不能下载 checkpoint | 只能下载自己 tenant 的 | ❌ | **ABAC**（资源 tenant_id 属性） |
| 能不能 SSH 进 Workspace | 只能进自己起的 Workspace | ❌ | **ABAC**（owner 属性） |
| 能不能查别人的 MLflow run | 同租户内可见 / 跨租户禁止 | ❌ | **ABAC**（资源 tenant_id 属性） |
| 训练用某个数据集 | 数据集所属租户 = 当前租户 | ❌ | **ABAC**（资源属性） |
| 工作时间外限制提交大作业 | — | ❌ | **ABAC**（环境属性） |

**结论**：RBAC 解决约 30%，剩余 70% 必须 ABAC（属性参与决策、ownership、资源属性、环境属性）。

### 为什么不用 Keycloak Authorization Services

| 原因 | 说明 |
|---|---|
| 资源注册爆炸 | Keycloak Authorization Services 要求每个资源（每个训练作业、每个 Workspace）注册为 Resource，资源量不可控 |
| JS Policy 弃用 | Keycloak 已弃用 JS Policy，复杂规则只能写 Java SPI；团队无 Java SPI 经验 |
| 性能 / 单点 | UMA 流程有 token exchange 开销，Keycloak 成为授权热点 |
| 与 design doc 分工冲突 | Keycloak 在 ADR-002 中明确职责为"认证 IdP"，授权逻辑应在 Tenant Service |

### PEP / PDP / PIP 角色映射

按 XACML 标准三角色框架：

| 角色 | 名字 | 职责 | 在本系统的归属 |
|---|---|---|---|
| **PEP** | Policy Enforcement Point | 拦截请求、调 PDP 拿决策、执行 allow/deny | Tenant Service Token Middleware + Handler 调用点 |
| **PDP** | Policy Decision Point | 评估规则、输出决策 | **本 ADR 的核心讨论对象** |
| **PIP** | Policy Information Point | 提供决策需要的属性 | Tenant Service Tenant Resolver / Quota Engine |

PEP 和 PIP 永远在 Tenant Service。本 ADR 决策的是 PDP 的实现选择。

## Decision

### v1：自研 PolicyEngine（Tenant Service 内）

- **位置**：Tenant Service 的 Service 层子模块
- **形态**：Python package，进程内调用，无远程网络开销
- **代码量**：核心实现约 200 LOC + 测试约 600 LOC

#### 接口设计（5 个方法，为 v2 切换 Cerbos 留路）

```python
class PolicyEngine(Protocol):
    """
    PolicyEngine 接口 — v1 自研实现 / v2 可替换为 Cerbos Adapter
    """

    def can(
        self,
        ctx: TenantContext,
        action: str,
        resource: Resource,
    ) -> Decision:
        """单次决策：返回 Allow / Deny + reason"""

    def can_batch(
        self,
        ctx: TenantContext,
        action: str,
        resources: list[Resource],
    ) -> list[Decision]:
        """批量决策：列表/筛选场景使用，避免 N 次调用"""

    def explain(
        self,
        ctx: TenantContext,
        action: str,
        resource: Resource,
    ) -> Explanation:
        """解释为什么 allow/deny —— 调试 + 审计用"""

    def list_allowed(
        self,
        ctx: TenantContext,
        actions: list[str],
        resource: Resource,
    ) -> set[str]:
        """给定资源，返回当前用户被允许的 action 集合 —— 给 UI 渲染按钮用"""

    def dry_run(
        self,
        ctx: TenantContext,
        action: str,
        resource: Resource,
    ) -> Decision:
        """不执行，仅返回决策 —— 给 SDK / CLI 预检使用"""
```

#### v1 内置规则（必须实现）

按 §3.2 硬纪律第 5 条优先级排列：

```python
# 1. 跨租户禁止（最高优先级，所有 action）
if resource.tenant_id != ctx.tenant_id:
    if "platform-admin" not in ctx.roles:
        return Deny("cross-tenant access denied")

# 2. 角色门槛（RBAC）
required_role = ROLE_MATRIX.get(action)
if required_role and required_role not in ctx.roles:
    return Deny(f"requires role {required_role}")

# 3. ownership（ABAC）
if action in OWNERSHIP_ACTIONS:
    if resource.owner != ctx.user_id and "tenant-admin" not in ctx.roles:
        return Deny("only owner or tenant-admin")

# 4. 资源状态（ABAC）
if action == "job.delete" and resource.status == "completed":
    return Deny("completed jobs cannot be deleted; use archive")

# 5. 配额（与 Quota Engine 协作）
if action.endswith(".submit"):
    quota_decision = quota_engine.check(ctx, action, resource)
    if not quota_decision.ok:
        return Deny(f"quota exceeded: {quota_decision.reason}")

return Allow()
```

#### 测试要求（写进 spec 001-tenant-identity）

- 单测覆盖：每条规则 ≥ 3 个用例（allow / deny / 边界）
- 集成测：跨租户访问 / ownership / 状态门槛 / 配额联动 共 4 类
- 性能测：单次决策 < 1ms（进程内）
- 总覆盖率 ≥ 90%（PolicyEngine 是安全关键路径）

### v2：评估迁移到 Cerbos

#### 触发重评的明确信号（任一即重评）

| # | 信号 | 说明 |
|---|---|---|
| 1 | 规则数量 > 30 条 | 自研规则维护成本超过 Cerbos YAML 学习曲线 |
| 2 | 第 2 个微服务需复用授权规则 | v1 只有 Tenant Service；若拆出独立 Inference Gateway 等需共享授权，集中 PDP 优势显现 |
| 3 | 非工程师角色（PM / 安全 / 合规）需改规则 | YAML 规则比 Python 代码更友好，可走 PR review 而非完整代码审查 |
| 4 | 出现复杂 ABAC（属性维度 > 3） | 如时间窗 + IP 范围 + 用户属性 + 资源属性同时参与决策，自研代码维护成本上升 |
| 5 | 合规要求规则与代码分离 | 审计需要"规则文件"独立可审；YAML + git 单独仓库满足这点 |

#### Cerbos 不能做、必须留在 Tenant Service 的事

| 工作 | 是否 Cerbos 范畴 |
|---|---|
| 创建 Keycloak Group / Capsule CR / OSS 子账号 / Gravitino schema / MLflow experiment | ❌ Tenant Service Lifecycle Orchestrator |
| 配额计数（已用 / 总） | ❌ Tenant Service Quota Engine |
| `tenant_id ↔ display_name` 解析 | ❌ Tenant Service Tenant Resolver |
| 资源命名规则映射 | ❌ Tenant Service Resource Mapper |
| 业务审计日志写入 | ❌ Tenant Service |
| **决策 alice 能否对 job-123 做 delete** | ✅ Cerbos PDP |

> Cerbos 是 PDP（决策引擎），不是资源管理器。引入 Cerbos 等于把 Tenant Service 的 PolicyEngine 子模块外置，**其他 4 个子模块**（Resolver / Quota / Mapper / Orchestrator）**没有任何变化**。

#### 假定的 v2 部署形态

```
ACK 集群
└── tenant-service Pod
    ├── tenant-service container       ← Python 服务（PolicyEngine 改为 Cerbos Adapter）
    └── cerbos sidecar container       ← gRPC localhost 调用，约 0.5ms
          └── 挂载 cerbos-policies ConfigMap（git-sync）
```

- Cerbos 无状态、无 DB
- 规则用 ConfigMap / Git Sync 分发
- 与 Keycloak 集成：principal attr 直接读 JWT claim

#### 替代候选（v2 重评时一并考虑）

| 引擎 | 模型 | 何时考虑 |
|---|---|---|
| **Cerbos** | ABAC | 默认候选 — YAML 规则、PR-friendly、与 Keycloak 集成天然 |
| OPA / Rego | ABAC | 如有跨基础设施统一策略需求（K8s admission + 应用授权），但 Rego 学习曲线陡 |
| OpenFGA | ReBAC | 当出现"项目 → 子项目 → 资源"嵌套关系图，且关系数 > 数千时 |
| Casbin | RBAC + ABAC | 多语言库；社区活跃度不如 Cerbos / OPA，不优先 |

## Consequence

### 正面

- v1 启动成本极低（约 200 LOC Python，无新组件 / 无 sidecar / 无运维负担）
- 接口已抽象（5 方法 Protocol），v2 切 Cerbos 是 implementation 替换，业务代码不动
- 与 Keycloak 职责边界清晰：Keycloak 认证（who you are）/ PolicyEngine 授权（can you do X on Y）
- 满足 §3.2 硬纪律第 4 条（强制走 PolicyEngine）+ 第 5 条（跨租户审计入口集中）
- 性能优势：进程内调用 < 1ms，无网络开销

### 负面

- v1 规则混在代码里，非工程师角色（PM / 安全）改不了规则 → 触发 v2 重评信号 #3
- 跨服务复用需要重复实现 → v1 只有 Tenant Service 单服务，暂无影响；触发 #2 时再切
- ABAC 规则数增长后，Python if/else 链路变长，可读性下降 → 触发 #1 时切
- 规则与代码混合，独立审计困难 → 触发 #5 时切

### 中性

- v2 切 Cerbos 时需要的工作量（预估）：
  - 写 cerbos_adapter.py（~100 LOC）
  - 把 builtin_rules.py 翻译成 YAML（按 v1 规则数 × 1 工时估算）
  - 部署 sidecar + ConfigMap + git-sync
  - 端到端测试（关键安全路径）
- v1 的接口设计（特别是 `Resource` 数据类的属性字段）必须考虑 Cerbos principal/resource attr 模型，避免 v2 切换时接口失配

## 实施约束（写入 spec 001-tenant-identity）

1. **强制走 PolicyEngine**：所有 handler 在执行业务逻辑前必须调 `policy_engine.can()`，CI 检查（grep handler 中是否漏调）
2. **Resource 数据类标准字段**：`tenant_id`、`owner`、`status`、`kind`、`id` 为必填；其他业务字段为可选 attr
3. **PolicyEngine 不读 DB / 不发网络**：所有决策依据来自传入的 `ctx + action + resource` 三参数（PIP 由调用方在外部预先填充好）— 这条是 v2 切 Cerbos 的关键前提
4. **审计**：每次 `Deny` 决策必须写入 audit log（含 ctx + action + resource + reason），用于安全分析
5. **`platform-admin` 跨租户操作**：必须走显式特权 API path（如 `/admin/*`），不允许在普通业务 path 中通过 role 绕过

## 后续动作

- [ ] Sprint 0a 0a-1：spec 001-tenant-identity 中包含 PolicyEngine 接口定义 + v1 内置规则清单（owner: P3）
- [ ] Sprint 0b 0b-7：Tenant Service 骨架包含 PolicyEngine Protocol（owner: P3）
- [ ] Sprint 1：PolicyEngine v1 实现 + 单测 / 集成测（owner: P3）
- [ ] Sprint 1+：每周回顾规则数；接近触发信号时启动 v2 评估
- [ ] v2 评估时机：Sprint 5 末或任一触发信号出现时（取较早者）
