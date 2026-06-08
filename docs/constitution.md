# Lite AI Infra — 架构宪法（Constitution）

> **状态**：Active（v1 起生效）｜**最后更新**：2026-06-06
> **来源**：ADR-002 / ADR-010 / ADR-011 / ADR-012 + design `docs/superpowers/specs/2026-05-08-llm-infra-platform-design.md`（§3.0 / §3.2）
> **性质**：**不可违反的硬纪律**。代码、计划、PR 与本文件冲突时，以本文件为准。

## 0. 元规则
- 优先级：**用户显式指令 > 本宪法 > superpowers 技能 > 默认行为**。
- 本宪法的任何变更**必须先改/加 ADR**，再同步本文件（与 `CLAUDE.md` 的引用）。
- 写代码 / 写计划 / 评审前都应对照本文件；CI 防线（§6）兜底机器强制。

---

## 1. 多企业租户与标识（ADR-010）
1. 层级固定为 **平台 → 企业(enterprise) → 用户组(group) → 用户**。
2. **`EnterpriseId` / `GroupId` 是独立类型**（Types 层），不与 `string` 互转；任何资源标识构造函数**只接收对应类型**。
3. 标识符：`enterprise_id = e-XXXX`（全局唯一）、`group_id = g-XXXX`（企业内唯一）。
4. **资源命名必须含 `enterprise_id`**（私有资源还须 `group_id`）；**`display_name` 严禁**出现在资源名 / 路径 / schema / index / label。
5. **资源归属编码在资源自身**（OSS 路径 / K8s label / MLflow tag / Gravitino schema 名），授权与过滤据此读取。
6. **硬隔离不变式**：非 admin 路径必须 `resource.enterprise_id == ctx.enterprise_id`；私有资源还须 `group_id` 匹配或 `enterprise-admin`；**跨企业仅 `platform-admin` 走显式特权 API**。

## 2. 身份与授权（ADR-002 / ADR-010 / ADR-011 / ADR-012）
1. 身份：**Keycloak 26.6.2**，**单一 realm + Organizations（企业）+ Group 子组（用户组+角色）**，**HA 双副本 + RDS 主备**。
2. **角色经 Group 子组路径编码**（`/e-x/g-y/{admins|members}`），随 token 的 `groups` claim 带出；**不用 Keycloak realm role 表达 scope**。
3. **token 仅认证**（user + 活跃企业 + groups）；**不承载授权决策**；角色/成员/资源属性由服务端解析/查取。
4. **授权唯一出入口：`PolicyEngine.can(ctx, action, resource)`**；**禁止散落 `if enterprise_id == ...`**。
5. 授权实现分期：**v1 薄 `can()`**（认证 + 企业隔离硬检查 + 基本角色门槛，in-code）→ **v2 Cerbos PDP**（ABAC / derived role，策略 in git）。`can()` 是 seam，替换 PDP **零改 handler**。
6. **Keycloak 不做授权**（不用 Authorization Services）。
7. **数据路径（OSS）不靠 PDP 内联执行**：Cerbos 只决策"发不发受限凭据"，阿里云 **RAM + STS** 路径级执行。
8. **LLM / Agent / Agentic Search 的数据与模型访问同样经 `can()` + scope 过滤**（ADR-012）。

## 3. 工程纪律（开发流程，不可违反）
1. **API 优先（API-first）**：任何服务 / 接口**先定契约（OpenAPI/proto）再实现**；**契约是接口的唯一真相源**，入 git、CI 校验 breaking、client 全生成（具体见 §4.2）。
2. **测试驱动（TDD）**：实现任何 feature / bugfix **先写测试**（红 → 绿 → 重构）；**无测试不合并**。授权 / 隔离 / 契约等关键路径必须有测试（如 AC-1~43）。
3. **完成前必验证**：声称"完成 / 修复 / 通过"前**必须跑验证命令并给出证据**；**证据先于断言**，禁止仅凭口头声称（superpowers: verification-before-completion）。
4. **计划先行**：多步任务**先出实现计划**（brainstorming → writing-plans → execute）再写代码；大改动设 review 检查点。
5. **隔离 + 评审**：功能在**独立分支 / worktree** 开发；**合并前过 code review**；不向 `main` 直接堆未评审改动。
6. **系统化调试**：遇 bug / 失败**先定位根因再改**，禁止猜测式打补丁（superpowers: systematic-debugging）。
7. **不静默砍范围**：任何降级 / 截断 / 抽样 / 跳过**必须显式记录**（日志 / PR 说明），不得让"覆盖了一部分"看起来像"全覆盖"。

## 4. 后端架构（design §3.0）
1. **微服务（按子系统全拆）+ API Gateway / BFF**；服务**独立部署、不共享 DB session**。
2. **API 优先**：每服务**契约（OpenAPI/proto）先行、入 git、CI 校验 breaking-change**；前端/SDK/CLI/服务间 client **全部由契约生成，禁止手写**。
3. **外部副作用**（Kueue / Volcano / Argo / Gravitino / OSS / Keycloak Admin API）**一律走 outbox / reconcile 幂等**，**禁止纳入同步链路阻塞主流程**。
4. 语言：控制面/数据/训练/推理服务 **Python 3.12（FastAPI）**；K8s controller **Go**；前端 **TypeScript + Next.js**；授权 PDP **Cerbos（不自写）**。**新增语言/改 Python 基线必须走 ADR**。
5. 3 人团队纪律：服务虽全拆，**共享统一脚手架**（FastAPI 模板 / CI / 可观测埋点）。

## 5. 运行时与交付纪律
1. **可观测性 by default**：每服务输出结构化日志 + 指标 + trace，**统一携带 `enterprise_id` / `group_id` label**；**无观测不上线**。
2. **安全 / 最小权限**：**密钥不进代码 / 仓库**（用 KMS / secret 管理）；RAM / STS **最小权限 + 短期凭证**；授权 **default-deny**（未明确允许即拒）。
3. **配置外置 + 环境对等**：所有配置经 env / ConfigMap，禁硬编码；**dev(docker-compose) / staging / prod 同构**（mock 仅替换本地不可得的依赖）。
4. **错误显式可解释**：决策 / 失败返回可解释 `reason`（进 4xx body + audit）；**fail fast**，不静默吞错。
5. **契约向后兼容 / 版本化**：对外 / 服务间契约的破坏性变更**必须版本化 + 留迁移期**；CI 拦截未版本化的 breaking（见 §3.1 / §4.2）。
6. **成本 / 配额意识**：LLM / GPU 等昂贵资源**用量必须计量**（按 enterprise / group）并可限流；v1 起埋点，硬限 → vN+（ADR-010/012）。
7. **数据迁移纪律（PG 回归后）**：schema 迁移**前向兼容 + 可回滚**，走迁移工具（Alembic）；**禁止手改生产 schema**。
8. **依赖 / 供应链（环境即工程）**：**Python 基线 3.12**，用 **uv** 管理——`.python-version` 钉解释器、`uv.lock` 锁依赖（可复现）；依赖与基础镜像**锁版本**；CI 用同一 lock 复现环境；CI 做兼容性 / 安全扫描（SBOM 轻量，vN+ 强化）。

## 6. 审计与数据（ADR-010）
1. **v1 审计**：mutation + `/admin/*` + `--force` + admin override **只追加写 OSS**（`oss://audit/...`，事后尽力）；同事务原子审计待 PG 回归。
2. **v1 无业务 PG**；**预算 / Quota Service / 同事务审计 / 中央资源元数据目录 → vN+（推迟）**。

## 7. 版本路线纪律
1. 路线：**v1 数据域 → v2 Agent 平台 + 统一 LLM 接入 → v3 Agentic Search → v4 微调 → v5 1B 预训练**。
2. **递增交付**，每版本独立可上线；时间线 **2026-06-06 → GA ≈ 2026-11-28**（~25 周）。
3. **版本号 `v1`–`v5` 专指功能里程碑**；"以后再做"一律写 **`vN+`（未来/后续）**；大写 **`V1`–`V12`** 是验收标准 ID，与版本号无关。
4. **推迟项不得偷偷提前**；任何扩范围 / 改路线**走 ADR**。

## 8. CI 防线（机器强制）
- **import-linter / dependency-cruiser**：依赖方向（分层不被破坏）。
- **grep**：`display_name` 不得出现在资源命名。
- **grep**：无散落的 `enterprise_id` / `group_id` 直接比较（必须经 `can()`）。
- **契约 breaking-change 校验**（`oasdiff` / `buf breaking`）。

---

## 变更管理
宪法条款变更流程：**提/改 ADR → 更新本文件 → 确认 `CLAUDE.md` 引用仍指向本文件**。三者须一致。
