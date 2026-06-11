# ADR-011: 授权 PDP 选型 — Cerbos（v1），取代 ADR-007 自研 PolicyEngine

- 状态：Accepted
- 日期：2026-06-04
- 决策人：平台团队（P1/P2/P3）
- 相关：**修订 ADR-007**（自研 PolicyEngine v1 / Cerbos v2 候选 → Cerbos 提前到 v1）/ ADR-010（多企业租户模型）/ design §3.2 硬纪律第 4 条 / design §3.9 PolicyEngine

---

## Context

- ADR-007 当初在"Keycloak Authorization Services vs 自研"之间选了自研，**未与现代开源 PDP 正面比较**。
- ADR-010 的多企业模型需要 **ABAC / ReBAC**（按企业/组 scope + 角色）。
- 身份/组织/角色已定为全在 Keycloak、随 token 的 `groups` claim 带出（ADR-010）；v1 无中央 PG。

### 候选评估

| 方案 | 形态 | scope 角色 | ABAC | 运维 | 结论 |
|---|---|---|---|---|---|
| 自研 | 进程内 | 自写 | 自由 | 0 依赖 | 自造测试/策略即代码 |
| PyCasbin | 进程内库 | RBAC-with-domains | 中 | 最轻 | 备选 |
| **Cerbos** | 无状态 sidecar | derived roles | 强(CEL) | 1 无状态进程 | **选定** |
| OpenFGA/SpiceDB | 有状态服务 | Zanzibar 关系 | 强 | 重(自带存储) | 规模/关系为主时升级项 |
| OPA | sidecar | 需自建 | 强(Rego) | 中 | 偏重 |

---

## Decision

### 1. PDP = Cerbos（v1）

- **无状态**：属性请求时传入，不存数据、无 DB；策略 YAML+CEL **入 git**，可单测、可评审。
- **derived roles** = 带 scope 的角色（`parentRoles` + condition 比对 enterprise/group/scope）。
- **Python SDK**，localhost gRPC。

### 2. PEP / PIP / PAP 分工（v1 无 PG 版）

| 组件 | 归属 | v1 数据来源 |
|---|---|---|
| **PEP** 执行 | Platform API 中间件 + 调用点 | — |
| **PDP** 决策 | **Cerbos** | 策略 in git |
| **PIP** 属性 | Platform API 组装 | **principal ← token 的 `groups` claim 解析**（`/e-x/g-y/admins` → 企业/组/角色）；**resource ← 资源自身**（OSS 路径 / K8s label / MLflow tag / Gravitino schema） |
| **PAP** 策略管理 | git + `cerbosctl` | — |

- **保留 `PolicyEngine.can(ctx, action, resource)` 唯一出入口**；内部调 Cerbos。**resource 属性来源做成抽象**：v1 从资源自身读，将来 PG 回归后改从 PG 读，handler 不变。

> **交付分期（2026-06-06）**：**阶段①**先用 **in-code 薄 `can()`**——认证 + 企业隔离硬检查（`resource.enterprise_id == ctx.enterprise_id`）+ 基本角色门槛，保证多租户安全底线；**阶段②**把 PDP 换成 **Cerbos**（细粒度 ABAC / derived role）。因 `can()` 是唯一出入口（seam），替换时 **handler 零改**。⚠️ 阶段①**不可省**企业隔离硬检查，可省的只是细粒度策略引擎。

### 3. Keycloak 不做授权

- 仅认证 + 携带组路径；**不用** Authorization Services（资源注册爆炸 / 26 起 JS policy 需 scripts flag+JAR / UMA 延迟）。

### 4. 资源建模（Cerbos resource kinds）

```yaml
mlflow_experiment { enterprise_id, group_id, scope }
dataset           { enterprise_id, group_id, scope }
training_job      { enterprise_id, group_id }
storage_grant     { enterprise_id, group_id, prefix }   # OSS 凭据申请作为资源
```

### 5. 执行模型分两类

| 资源 | 走 Platform API | Cerbos 角色 | 实际执行 |
|---|---|---|---|
| MLflow / 数据管线 / 训练作业 | ✅ 控制路径 | 直接判 | Platform API PEP |
| **阿里云 OSS**（客户端直连）| ❌ 数据路径 | 决策"发不发受限凭据" | **阿里云 RAM + STS 短期受限凭据**（路径级），或预签名 URL |

> OSS 授权的是 **"申请某前缀 STS 凭据"这个动作**（走 API，Cerbos 管得到），而非每次对象读写。

### 6. 审计 + 部署

- **审计（v1）**：Cerbos decision log（每次 allow/deny）+ Platform API 业务审计**只追加写 OSS**（`oss://audit/...`），可选 Fluent Bit 索引 OpenSearch。**无 PG**（详见 ADR-010 §5）。
- **部署**：Cerbos 无状态容器（sidecar / Deployment），策略从 git bundle / ConfigMap 加载，可水平扩。
- 查询过滤（"列出我能看的 X"）在数据层按 `enterprise_id/group_id` 过滤，与 PDP 无关。

---

## Consequences

### 正面
- 策略即代码 / 可测试 / 可审计；`can()` seam 使 PDP 可替换。
- **principal 全部来自 token，resource 来自资源自身 → v1 完全不需要 PG**。

### 负面 / 代价
- 多一个无状态 sidecar；YAML+CEL 小学习成本。
- token stale：角色（子组）变更要等 token 刷新生效（短 TTL 缓解）。

### 升级路径
- 中央元数据 PG 回归后，PIP 的 resource 属性改从 PG 读（接口不变）。
- 关系型授权成主导 / 规模大 → OpenFGA / SpiceDB（仍藏 `can()` 后）。

### 行动项
- **Sprint 0 spike（半天）**：Cerbos Python SDK + derived roles + 从 token `groups` 解析 principal，跑通 2–3 个典型 AC；SDK/版本现状以 spike 为准。

---

## 附录：Cerbos 策略骨架（示例）

```yaml
# derived_roles/tenant_roles.yaml — 带 scope 的角色
apiVersion: api.cerbos.dev/v1
derivedRoles:
  name: tenant_roles
  definitions:
    - name: enterprise_admin
      parentRoles: ["enterprise-admin"]
      condition: { match: { expr: R.attr.enterprise_id == P.attr.enterprise_id } }
    - name: same_group_member
      parentRoles: ["member", "group-admin"]
      condition:
        match:
          all:
            of:
              - expr: R.attr.enterprise_id == P.attr.enterprise_id
              - expr: R.attr.group_id in P.attr.group_ids
    - name: shared_reader
      parentRoles: ["member", "group-admin", "enterprise-admin"]
      condition:
        match:
          all:
            of:
              - expr: R.attr.scope == "shared"
              - expr: R.attr.enterprise_id == P.attr.enterprise_id
---
# resource_policies/training_job.yaml
apiVersion: api.cerbos.dev/v1
resourcePolicy:
  resource: training_job
  version: default
  importDerivedRoles: ["tenant_roles"]
  rules:
    - actions: ["submit", "cancel", "view"]
      effect: EFFECT_ALLOW
      derivedRoles: ["same_group_member"]
    - actions: ["*"]
      effect: EFFECT_ALLOW
      derivedRoles: ["enterprise_admin"]
```

> `P`/`R` = `request.principal`/`request.resource`。principal 的 `roles` 与 `attr`（enterprise_id/group_ids）由 PEP 从 token 的 `groups` claim 解析后填入。

## 附录:Spike B 结论(2026-06-10,本地 Cerbos 容器实测)

`ghcr.io/cerbos/cerbos:latest` + `spikes/cerbos_seam/`(policies: derived_roles/job/dataset;脚本 `spike_b.py`):

- **同一 `can(ctx, action, resource)` 签名**实现了 Cerbos 后端(`cerbos_can`),与 v1 薄引擎在 AC-1/AC-2/AC-6/AC-9 四条上**逐条一致**(allow/deny 完全相同)。
- **`services/gateway/app.py` 零改成立**:gateway 只 import `libs.authz.engine.can`;v2 切换 = 替换 engine 内部实现(in-code 规则 → Cerbos HTTP check),handler 与签名均不动。
- Context.memberships → Cerbos principal.attr 映射直接(数组 + `exists()` CEL 表达式),derived roles 可表达 owner/同组成员/组管理员/同企业四类语义。

**判定:go** —— ADR-011 的 seam 设计验证成立,v2 接 Cerbos 无架构风险。
