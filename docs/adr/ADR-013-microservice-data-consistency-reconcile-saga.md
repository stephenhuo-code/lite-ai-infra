# ADR-013: 微服务数据一致性 — 无共享 DB + reconcile/saga（取代"同事务原子"）

- 状态：Accepted
- 日期：2026-06-06
- 决策人：平台团队（P1/P2/P3）
- 相关：补充/修订 design §3.0（微服务）/ §3.10（配额）/ §3.11（审计）/ §3.12（状态机）；ADR-010（v1 无 PG）/ ADR-011（Cerbos）；constitution §4 / §6

---

## Context

- 已决策**维持"按子系统全拆微服务、服务独立部署、不共享 DB session"**（constitution §4.1）。
- 但原 design 的若干一致性机制建立在**单体内 PG 同事务**之上：
  - §3.10 配额"原子预留"（reserve/confirm/release，PG 行锁 + 同一 SQLAlchemy 事务）；
  - §3.11 审计 `@audited` 装饰器（audit 与业务 mutation **同一 PG 事务**，写失败回滚）；
  - §1.2 ⑫ Admission Pipeline 的 "audit + outbox 同 PG 事务"。
- 全拆微服务 ⇒ **没有跨服务共享事务**；且 **v1 无业务 PG**（ADR-010）。
- 评审（product-architect, 2026-06-06）指出两点硬伤：① "v1 无 PG → 微服务可行"的论证在 **PG 回归后崩**（跨服务事务是分布式难题）；② **outbox 模式本身需要 PG 同事务**（业务状态 + 事件表同写），与"v1 无 PG"矛盾。

本 ADR 解决"全拆微服务下数据一致性怎么做"，并取代上述"同事务原子"的旧假设。

---

## Decision

1. **不依赖跨服务 / 同进程 DB 事务做一致性。** 每服务自治其数据（PG 回归后 **per-service schema/DB**，不共享 session）。
2. **外部副作用（Kueue / Volcano / Argo / Gravitino / OSS / Keycloak Admin API）走 reconcile**（声明式期望状态 + controller 拉平），而非同步阻塞调用：
   - **v1**：以 **reconcile 为主**（无 PG，outbox 的"同事务事件表"前提不成立）。
   - **PG 回归后**：单服务内部可用 outbox（**本服务事务 + 本服务事件表**）；**跨服务一致性用 saga**（编排/协同 + 补偿动作），**不做分布式两阶段提交**。
3. **配额（vN+）**：放弃"跨服务同事务原子预留"；改为"服务自治账本 + reconcile 校正"，admit-time 由 Kueue 兜底。
4. **审计**：v1 OSS 追加写（事后尽力，非原子，ADR-010 §5）；PG 回归后**单服务同事务写本服务 audit**，跨服务用 `request_id`/关联 id 串联，**不强求全局原子**。
5. **幂等是一等公民**：所有副作用按业务键（如 `workload_id`）幂等；reconcile 可重入、可重放。

---

## Consequences

### 正面
- 服务真正解耦、可独立部署/扩缩；**用 reconcile/saga 替代分布式事务**，避免 2PC 复杂度。
- 与 v1 无 PG、ADR-010/011 一致。

### 负面（接受）
- **放弃"全局同事务原子"** → 存在短暂不一致窗口（**最终一致**）；审计/配额在 v1 尤其非强原子。
- 需要额外的 **reconcile / nightly 对账 job**、补偿逻辑。
- **合规口径**：审计"无操作不留痕"在 v1 是"尽力"，强保证待 PG 回归且仅单服务内（对外多企业 SaaS 上线前需在风险表登记）。

### 取代关系
- design §3.10"PG 同事务原子预留"、§3.11"@audited 同事务"、§1.2 ⑫"audit+outbox 同 PG 事务" → 在微服务下**不成立**；标 vN+/仅单服务内适用，**以本 ADR 为准**。

---

## 备选（未采纳）
- **模块化单体**（同进程可同事务，一致性最简）—— product-architect 推荐，但团队选择**维持全拆微服务**（见会话决策），因此接受本 ADR 的"最终一致 + reconcile/saga"代价。若未来一致性成本过高，可重新评估单体化（走新 ADR）。
