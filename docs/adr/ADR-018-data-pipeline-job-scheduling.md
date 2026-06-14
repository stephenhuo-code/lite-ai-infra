# ADR-018: 数据管线作业调度 — S1 无框架薄壳 + JobRunner seam,S2a 演进至 Argo(否决 Prefect)

- 状态：Accepted（2026-06-14，owner）
- 决策人：owner
- 相关：ADR-013(微服务数据一致性 — 外部副作用走 reconcile;v1 无 PG)、ADR-009(训练调度 Volcano vs Ray)、ADR-016(Gravitino 租户映射);constitution §1(隔离)/ §2.4(can() 唯一出入口)/ §3.0.2(契约先行)/ §4(v1 容忍单机)/ §6(审计);S1 设计 spec §2(架构决策 2/5)、§8(用户自定义管线三层)、§9.1(data-pipeline-service 边界);Plan 5

---

## Context

`data-pipeline-service`(Plan 5,S1 服务化)的契约要求 **`POST /v1/data/prepare`(submit→立即返回 job_id)+ `GET /v1/data/jobs/{id}`(查状态)**。但其后端 `pipelines/data_prep.run_prepare` 是**分钟级同步长跑**(tar→jsonl→Data-Juicer/Ray 子进程→Lance on OSS),不能在一次 HTTP 请求里阻塞返回。

约束(既有决策,非本 ADR 新设):
- **v1 无 PG**(ADR-013):作业状态不能落库;ADR-013 同时定调"外部副作用走 **reconcile**(声明式期望状态 + controller),而非同步阻塞"。
- **v1 无 K8s/ACK**(spec §0/§6):Argo/Kueue/Volcano 等 K8s 原生编排**明确推 S2a**。
- **S1 单机**(spec §2.2):"管线与服务解耦……服务只做提交/查状态薄壳(S1 **进程内/subprocess 调度**,Argo 推 S2)。**服务挂,管线不挂**。"
- **隔离是宪法红线**;`can()` 是授权唯一出入口(§2.4);资源命名只含不透明 ID(§1.4)。
- spec §8:用户自定义管线分三层演进 —— Layer 1(配方/算子,Plan 2 已支持,本服务暴露)、**Layer 2(用户自带容器步,跑在企业隔离 ns,S2a 配 Argo)**、Layer 3(自定义 DAG,vN+)。

核心问题:**S1 用什么承载"提交/查状态",才能既最省、又能平滑长成 S2a 的 Argo?**

调研结论(2026-06-14):
- **Data-Juicer 自身不是调度器**。DJ 2.0 的 `service.py` 只把算子暴露为 HTTP 端点,无 submit→job_id→状态轮询。不适合做作业层。
- **Ray Jobs API** 可复用(DJ 执行器本就是 Ray,自带 job_id/status/日志),但对一次性 S1 薄壳属过度工程,且多一层 Ray 头节点网络/拓扑依赖。
- **重型编排器(Argo/Prefect/Airflow/Dagster/Celery)** 是 S2 形态,S1 引入即净增基础设施且会被取代。

## Decision

### 1. S1:不引入任何调度框架,用"无框架薄壳"

`data-pipeline-service` 的 S1 形态 = **detached 子进程 + 状态文件 JobStore + 单槽串行队列**:

- `POST /v1/data/prepare`:同步过 `can()`(deny→403,**零副作用** + 审计 deny)→ 生成不透明 `job_id`(uuid)→ 写 `queued` 状态文件 → 入队 → 立即返回 `202` + Job。
- 单槽**串行**调度器(`SubprocessJobRunner` **自管**后台线程,owner 决策"串行单作业排队"):空槽时取最旧 `queued` → spawn **detached** worker 子进程 → 标 `running`。调度全程持 `threading.Lock`(handler 线程与后台线程并发安全,防同一作业被 spawn 两次 / 破坏单槽);dispatch 前先跑 **PID 存活看门狗**:status=running 但 worker PID 已死(OOM/硬杀绕过 except)→ 标 `failed` 释放槽,防单槽队列死锁。
- worker = service 层入口 `python -m services.data_pipeline_service.worker`,调 `pipelines.run_prepare`(内部**再过一次 `can()`** = 纵深防御,且本就有 + 审计 allow/fail),终态写 `succeeded{rows_written,lance_uri}` / `failed{error}` 状态文件。
- `GET /v1/data/jobs/{id}`:`can(data.read)` 按 job 的企业/组判 → 读状态文件返回。

detached 子进程保证 **"服务挂,管线不挂"**(spec §2.2);状态文件保证重启后仍可查(无需 PG)。

### 2. 稳定边界 = 契约 + `JobRunner` 端口;五条不变量现在定死

可演进性来自**抽象边界**,不来自后端引擎。Plan 5 必须固化:

| # | 不变量 | 为何决定平滑演进 |
|---|---|---|
| 1 | **异步 submit/poll 契约**(POST 立即返 job_id;GET 轮询;绝不同步阻塞) | Argo 同为异步提交+轮询 → 换引擎不动契约 |
| 2 | **`JobRunner` 端口**:`submit(spec)->job_id`、`get(id)->JobRecord` **都走它**;handler 不直接 spawn/读文件。调度/队列推进(`dispatch`/后台线程/PID 看门狗)是 `SubprocessJobRunner` **私有**,不进端口、不进 runtime(`main.py` 仅 `build_app(runner=…)`) | S2a 唯一切换点 = 实例化哪个 runner(`SubprocessJobRunner→ArgoJobRunner`);契约/handler/runtime 编排不变 |
| 3 | **job_id 服务端生成、不透明字符串**(§1.4) | uuid / Argo workflow name / Ray submission-id 语义一致可互换 |
| 4 | **后端中立状态模型,现在即含 `queued`;且 `Job` 带派生 `terminal: bool`** | 客户端按 `terminal` 判终态(非枚举字符串匹配)→ S2a 加 `cancelled` 等新终态时轮询逻辑不破坏 |
| 5 | **`can()`/审计在同步边界**(deny→403 零副作用)**+ worker 内再判一次** | Argo 化后:服务 submit 处 `can()`,workflow step 内再判。worker 复检用**提交时角色快照** = 防 handler bug 的纵深防御,**非授权新鲜度保证**(见 Consequences) |

契约 0.x **字段从宽**(spec §52),S2a 的 per-shard 重试/取消/日志端点/并发均为**加法**演进。

### 3. S2a 调度框架选 **Argo Workflows**,否决 Prefect

| 维度(按宪法硬约束排序) | Argo | Prefect | 结论 |
|---|---|---|---|
| 多租户隔离(宪法红线) | 每步=Pod,原生吃 ns/RBAC/NetworkPolicy/securityContext | 隔离粒度弱,需在其上重造 | **Argo** |
| 用户自带容器步(spec §8 Layer 2) | DAG 一步=容器镜像,原生模型 | 单位是 Python task,跑用户容器别扭 | **Argo** |
| K8s/ACK 既定方向 + KubeRay/Kueue/Volcano 协同(ADR-009/013) | K8s 原生 CRD,同栈协同 | K8s 无关,不与批调度原生编排 | **Argo** |
| 声明式 reconcile(ADR-013) | Workflow=声明式 CRD,controller reconcile | 控制平面命令式推任务 | **Argo** |
| 一人团队 DX | YAML/CRD 偏重 | Python 原生,DX 更好 | Prefect(唯一赢点) |

**判据:本项目是多租户平台,不是内部数据团队 —— DX 输给隔离是应有取舍。** 仅当同时"砍掉 §8 Layer 2/3 用户容器/自定义 DAG 野心 + 优先 DX + 不纳入 Kueue/Volcano/KubeRay"时才改选 Prefect;三条均不成立 → Argo。`JobRunner` 端口下 S2a 落 `ArgoJobRunner`(workflow step 内 `can()` 复检,Lance 写入仍平台执行)。

## Consequences

**正面**:S1 零新增基础设施(无 PG/无 broker/无 K8s);契约/SDK/CLI(Plan 6)/S2c 前端在演进中不变;`can()` 唯一出入口与审计纪律全程保持;与 ADR-013 "外部副作用走 reconcile/外部运行时" 同向。

**负面 / S1 已知限制**(均在 Plan 5 与 runbook 标注,S2a 解决):
- 单副本;**queued 队列推进依赖服务在线**(running 的 detached 作业不受服务重启影响,但排队中的不会自行推进)。
- **孤儿 `running` 会卡死单槽队列**:worker 被 OOM/硬杀(绕过 except)→ 状态永停 `running` → `running_count()>0` 永真 → 后续 `queued` 全部死锁。S1 缓解 = dispatch 内 **PID 存活看门狗**(死 PID 的 running 标 `failed` 释放槽);跨服务重启的声明式自动对账(reconcile)仍属 S2a。
- **提交后授权撤销窗口**:提交后、worker 执行前调用者角色被撤销,worker 用快照角色仍通过复检(授权新鲜度依赖 token 生命周期/Spike A);非授权新鲜度保证,S1 可接受,S2a 同。
- `tar_dir` 在 S1 为**管线宿主机上的 ops 路径**(贴合 Plan 2 现状);S2a 改为按数据集名解析 OSS `raw/` 引用(契约加法收紧)。
- 无取消/无 per-shard 重试(Argo 在 S2a 免费提供)。

## Alternatives considered

- **同步执行**:违反不变量 1(submit→job_id),HTTP 超时风险。否决。
- **进程内线程 + 内存状态**:违反 spec §2.2 "服务挂管线不挂"(重启丢在跑作业)。否决。
- **Ray Jobs API(S1)**:可复用既有 Ray、白送状态/日志,但对会被 Argo 取代的 S1 薄壳过度工程 + 多一层 Ray 网络/拓扑依赖。**推迟**;若 S1.x 需要更标准的提交/日志面再评估(同在 `JobRunner` 端口下)。
- **Celery/RQ + Redis(S1)**:单机串行不值当引入 broker。否决。
- **Prefect(S2a)**:见上表,隔离/容器步/K8s 原生三项不敌 Argo。否决,理由留档以备追溯。
