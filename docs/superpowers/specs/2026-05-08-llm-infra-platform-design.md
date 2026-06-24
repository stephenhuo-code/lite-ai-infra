# Lite AI Infra Platform 设计文档

> **状态**：Draft（多公司 SaaS 架构；v1 起多企业 + 版本递增 v1/v2/v4)
> **作者**：平台团队(原按 3 人编制;**2026-06 起实际为一人 + Claude**,见文末修订记录)
> **日期**：2026-05-08(修订 2026-06-12)
> **目标上线**：v1 原 ≈2026-07-11(**将后移**,S2 计划时走 ADR 重排,宪法 §7.4);GA 原 ≈2026-11-28
> **执行现状**:S0 已关闭(ADR-014 carry-over);S1——出口①②③ 已验收,**出口⑤ 已关闭**(2026-06-24,真 GUI 经 BFF 全链路调通;Plan 8 前端 + catalog-driven + owner 模型合并 main)—— 见 §5.3 各 sprint 修订块、S1 design §9.3 计划序与文末"修订记录"

> **as-built 修订(2026-06-24,以 ADR 为准)**:本文为全平台**愿景**(含 Workspace/配额/Cerbos/CLI 等尚未建部分),下述**已实现并合并 main**的部分,口径已被后续 ADR 收敛:
> - **数据集归属 = owner(上传用户 sub),非 group**([ADR-024](../../adr/ADR-024-owner-based-dataset-ownership.md),amend ADR-010/011/016)。**数据集** OSS 路径 = `e-XXXX/{user}/{raw,processed}/…`(不再 `e-0001/g-0001/…`)。**group 退为访问/审计维度**(跨用户分享/group 访问 → Cerbos v2);企业仍硬隔离。
> - **Gravitino 映射 = metalake `e_XXXX` / catalog `data` / schema `datasets`,每数据集 = 一个 fileset**([ADR-016](../../adr/ADR-016-gravitino-tenancy-mapping.md)),**非** `e_0001_g_0001` schema。catalog 为数据集位置真相源,管线按名查 catalog 拿 location([ADR-023](../../adr/ADR-023-catalog-driven-datasets.md));location 记 `s3a://`(HCFS),lance 读写用 `s3://`。
> - **仍成立(本次未改)**:K8s/Kueue 命名空间、配额、Keycloak `/e-XXXX/g-YYYY/{admins,members}` 结构、Cerbos+STS 路径级访问控制、group-admin 角色 —— 这些是 group 维度的**访问/计算/组织**用途,与"数据集归属"正交。
> - **v1 已实现**:数据管线(DJ→Lance)+ 元数据(Gravitino)+ BFF + React 控制台 + catalog-driven + owner 模型;全链路 live 验收通过。下文凡涉数据集归属/Gravitino schema 的旧写法,以本 callout + 对应 ADR 为准。

---

## 0. Executive Summary

### 项目定位
公司级共享 **多模态数据 + Agent + LLM 应用**平台，**对外多公司 SaaS**（架构从第一天起多企业，ADR-010）。**按版本递增交付：v1 = 数据域（数据管线/元数据/多模态处理）→ v2 = Agent 开发平台 + 统一 LLM 接入（Claude/Codex/Minimax，API key 按 token 计费）→ v3 = Agentic Search（多源多模态统一检索）→ v4 = 微调（SFT/LoRA）→ v5 = 1B 预训练**。战略上**先用第三方 LLM + Agent 快速交付价值，自研微调/预训练后置**。通过 Keycloak 做身份/企业管理，所有资源标识与企业名解耦，扩展到 5+ 企业**不需要重命名任何资源**。

### 核心架构原则（写进 constitution）

> ⚠️ **模型已升级为多企业 SaaS（2026-06-04，见 [ADR-010](../../adr/ADR-010-multi-enterprise-tenancy-model.md) / [ADR-011](../../adr/ADR-011-authorization-pdp-cerbos.md)）。** 原扁平 `enterprise_id` 升级为 **`enterprise_id` + `group_id` 两级**；以下及全文残留的 `enterprise_id` 表述为历史单层模型，映射关系见 ADR-010，术语全面替换为后续工作。

> **资源标识用不透明的 `enterprise_id`（+ 私有资源 `group_id`），公司名/组名只是 Keycloak Organization/Group 里的 `display_name`。**
> 所有 OSS 路径、K8s namespace、Gravitino schema、模型 URI 一律使用 `enterprise_id`/`group_id`；`display_name` 仅出现在 UI、日志、文档中。

> **层级**：平台 → 企业 → 用户组 → 用户。**身份+组织+成员+角色** = Keycloak 单一 realm（企业=**Organization**；用户组+角色=**Group 子组** `/e-x/g-y/{admins|members}`，随 token 的 `groups` claim 带出）；**授权** = **Cerbos** PDP（principal 来自 token，resource 属性来自资源自身：OSS 路径/K8s label/MLflow tag/Gravitino schema）；**审计** = 只追加写 OSS（v1）；**预算 / 中央元数据(PG) v1 推迟，需要时引入**；**企业硬隔离**落在资源命名 + 授权层。

### 核心约束
- **3 人**，**~25 周**（2026-06-06 → ≈2026-11-28）；版本递增交付（v1→v5），每版本可独立上线
- **环境拓扑**：
  - **prod**：阿里云 ACK + OSS（不使用 PAI / PAI-DLC）
  - **dev**：本地 Docker Compose（MinIO 替 OSS、kind/k3d 可选替 K8s、CPU 替 GPU、mock 跳过 Volcano/Argo）
  - **staging**：ACK 小集群（与 prod 同构，e2e 测试用）
- **身份**：Keycloak 26.6.2（HA 双副本，单 realm + Organizations，ADR-002/010）
- **数据栈**：Ray Data + Data-Juicer + Lance（开源）
- **训练栈**：PyTorch DDP / DeepSpeed；Megatron 通过镜像契约**未来**接入
- **元数据**：Apache Gravitino（资产 catalog）+ MLflow（实验跟踪）
- **首个企业任务**：10TB 图文，1B 多模态，单节点 8 GPU，3-4 天训练

### 战略路线
**路线 1（垂直优先）+ 路线 2（最大化用 OSS）+ 多企业架构从 v1 起**：
- 范围：首个客户只有 X-user team（一个企业落地），架构完整支持多企业
- 实现：所有可用 OSS 都用，3 人聚焦"粘合 + 身份/组织层 + SDK + 前端"
- 多企业：首发单企业落地但架构完整；后续版本仅扩展企业数量、不动资源命名

> **版本路线（2026-06-06 修订）**：**v1 数据域** → **v2 Agent 平台 + 统一 LLM 接入** → **v3 Agentic Search** → **v4 微调（SFT/LoRA）** → **v5 1B 预训练**。身份/组织/授权/SDK/监控/网关等基础设施贯穿、随 v1 最先就位。**递增交付**（时间线见 §5）。

### 交付目标（一句话）
**首个客户 X-user team 沿版本递增获得价值：v1（10TB 多模态数据准备 → 清洗/处理 → Lance + Gravitino 元数据）→ v2（Agent 平台 + 统一 LLM 接入，用 Claude/Codex/Minimax API（按 token 计费）做模型/管线/数据探查）→ v3（Agentic Search 多源多模态统一检索）→ v4（基于现成基座 SFT/LoRA + 推理）→ v5（1B 多模态预训练，8 GPU，3-4 天）；每个版本可独立交付验收；节点故障 1h 内自动恢复；任意资源标识不含企业/团队名。**

---

## 1. 子系统分解

### 1.1 整体分层

```
┌─────────────────────────────────────────────────────────────┐
│ 用户接入层（自研）                                          │
│   ① Platform Portal + SDK + CLI                             │
│   ⑨ Dev Workspace（code-server + Remote-SSH）               │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 身份 / 企业层（v1 必做）                                     │
│   ⑩ Keycloak 26.6.2（OIDC IdP + Organizations=企业 + 授权）  │
│   ⑪ Org Service（解析 groups claim → enterprise/group/role）│
│   授权：薄 can()(v1) → Cerbos PDP(v2)                        │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 控制平面（微服务 + API 优先）                               │
│   ② 配额（Kueue Cohort=企业 / LocalQueue=组）               │
│   ③ 实验元数据（MLflow 集成）                                │
│   API Gateway/BFF + 各子系统服务（FastAPI）                 │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ AI 应用平面（v2 / v3 新增）                                  │
│   ⑮ 统一 LLM 接入服务（LLM Gateway，LiteLLM 待选型）         │
│      接 Claude / Codex / Minimax API（按 token 计费） + 路由/计量/密钥/限流  │
│   ⑯ Agent 平台 + 统一对话交互（v2）                          │
│      模型开发 / 管线开发 / 数据探查 agent，复用第三方模型    │
│   ⑰ Agentic Search（v3）：多源多模态数据统一检索 agent      │
└─────────────────────────────────────────────────────────────┘
              ↓                    ↓                  ↓
┌──────────────────┬──────────────────┬──────────────────────┐
│ 数据平面         │ 训练平面          │ 推理平面             │
│ ④ 数据管线       │ ⑥ 训练运行时     │ ⑧ 推理服务（v1 必做）│
│   Ray Data +     │   K8s Job +      │   vLLM / TEI         │
│   Data-Juicer    │   Volcano +      │                      │
│ ⑤ 数据存储+目录  │   torchrun       │                      │
│   OSS + Lance    │ ⑦ Checkpoint     │                      │
│   + Gravitino    │   OSS + 自动恢复 │                      │
│   (按 enterprise_id) │                  │                      │
└──────────────────┴──────────────────┴──────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 支撑平面                                                    │
│   Ⓐ 监控（Prometheus + Grafana + DCGM）                     │
│   Ⓑ CI（GitHub Actions + ACR）                              │
│   Ⓒ 日志（OpenSearch + Fluent Bit + Grafana，自建）          │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 子系统职责矩阵

| # | 子系统 | 职责 | v1 形态 |
|---|---|---|---|
| ① | 前端 + API Gateway/BFF + SDK + CLI | 完整前端页面（数据域优先）；提交作业、查询、列表；自动注入 enterprise_id/group_id | 自研，**完整前端**（**React + Vite**,ADR-019;gateway BFF serve dist）+ API Gateway/BFF（OIDC 会话）；SDK/CLI 由 OpenAPI 契约生成（CLI 推迟为 ops 工具,ADR-019） |
| ② | 配额 | 按 enterprise_id 隔离 Kueue 配额 | LocalQueue per enterprise/group |
| ③ | 实验元数据 | 训练参数/指标/artifact tracking | MLflow 单实例（experiments 按 enterprise_id 分组） |
| ④ | 数据管线 | 10TB 图文清洗 → Lance | Ray Data + Data-Juicer + Argo |
| ⑤ | 数据存储 + 目录 | 数据/模型资产管理（按 enterprise_id 分区） | OSS + Lance + Gravitino |
| ⑥ | 训练运行时 | 1B 预训练 + SFT | K8s Job + Volcano + torchrun + DDP/DeepSpeed |
| ⑦ | Checkpoint + 容错 | 训练故障恢复 | OSS ckpt + Volcano gang restart |
| ⑧ | 推理服务 | HTTP API 推理 + embedding | vLLM + TEI |
| ⑨ | Dev Workspace | 浏览器 VSCode + Remote-SSH | code-server + sshd Pod |
| **⑩** | **Keycloak** | **OIDC IdP + 身份/组织/成员/角色真相源（Organization=企业，Group 子组=用户组+角色，进 token）** | **StatefulSet 26.6.2 + RDS PG** |
| **⑪** | **Org Service** | **薄层封装 Keycloak Admin API（开通企业/组、加移成员）+ token 校验中间件（解析 groups claim → enterprise_id/group_id/role）** | **Platform API 内置模块** |
| Ⓐ | 监控 | GPU/作业/IO/平台健康 | Prometheus + Grafana + DCGM |
| Ⓑ | CI | 平台代码 + 镜像构建 | GitHub Actions + ACR |
| Ⓒ | 日志 | 集中日志查询 | OpenSearch **3 节点 cluster（v1）+ security plugin + ILM**（见 §3.16.1）+ Fluent Bit 采集 + Grafana 可视化（详见 ADR-005） |
| **⑫** | **Admission Pipeline** | **准入中间件链：① PolicyEngine（`can(ctx, action, resource)` → 调 **Cerbos**，ADR-011）→ ② ~~QuotaService~~（**v1 推迟**，无 PG 预算账本，仅 Kueue 静态配额）→ ③ Audit（**v1 追加写 OSS**）+ 外部副作用 **reconcile**（v1 走声明式 reconcile；PG 回归后单服务内 outbox + 跨服务 saga，ADR-013）；**禁止**把 Kueue/Argo/Volcano/Gravitino/OSS 调用纳入同步链路；详见 §3.9/§3.11** | **Platform API 中间件链 + Cerbos sidecar + OSS audit + reconcile controller；v1 无 PG（配额账本/同事务审计/outbox 推迟，ADR-013）** |
| **⑬** | **Enterprise Provisioner** | **开通/暂停/归档企业时 reconcile：Keycloak Organization + Group 子组骨架（含角色）/ Kueue LocalQueue+Cohort / OSS prefix + RAM/STS / Gravitino schema / MLflow experiment / Grafana org / OpenSearch index template（v1 推迟：PG 元数据/配额账本）** | **controller-runtime 风格 reconciler，幂等；经 Keycloak Admin API 建 Org/Group** |
| **⑮** | **统一 LLM 接入服务（LLM Gateway）** | **对所有第三方/自托管模型的统一 API（chat/completion/embedding）：模型路由、API key 管理、限流、按 enterprise/group 计量、回退**；接 **Claude / Codex / Minimax API（按 token 计费）** 等 | **LiteLLM 待选型（候选）；独立微服务；策略经 §3.2 授权** |
| **⑯** | **Agent 平台 + 统一对话交互** | **Agent 开发框架 + 运行时 + 统一 chat UI**；内置 agent 用于**模型开发 / 管线开发 / 数据探查**（复用第三方模型，经 ⑮）；工具调用走 Platform API 契约 | **自研（v2）；前端统一对话入口 + 后端 agent 运行时** |
| **⑰** | **Agentic Search** | **一个 agent 对集成的多源多模态数据（OSS/Lance/Gravitino/MLflow…）做统一检索**：规划→多模态检索→综合→引用 | **自研（v3）；复用 ⑮ LLM + v1 数据/向量** |

### 1.3 三人分工

| 角色 | 负责子系统 |
|---|---|
| **P1**（平台/K8s/训练/推理重） | ⑥ ⑦ ⑧ ⑨ ② Ⓐ Ⓑ |
| **P2**（数据重） | ④ ⑤ + Lance VectorTable 抽象 |
| **P3**（产品/集成重） | ① ③ ⑩ ⑪ + Anchor team 接口人 |

---

## 2. MVP 范围切片

### 2.1 验收标准（按版本）

> 各版本独立验收。**版本归属**：**v1** = 数据域（1、6、8、架构标准 9）→ **v2** = Agent 平台 + 统一 LLM 接入（10）→ **v3** = Agentic Search（11）→ **v4** = 微调/推理（3、4、5）→ **v5** = 1B 预训练（2）。

1. **数据**：10TB 原始图文 → Data-Juicer 清洗 → Lance 数据集 → Gravitino 注册（按 enterprise_id/group_id schema）
2. **预训练**：SDK 提交 1B 多模态预训练，单节点 8 GPU DDP，3-4 天完成
3. **微调**：基于现成基座（或已有模型）提交 SFT/LoRA，新模型版本登记
4. **推理**：微调模型部署成 HTTP 服务（vLLM），有 P95 延迟基准
5. **容错**：训练中断能从 ckpt 自动恢复，丢失进度 ≤ 1 小时
6. **可观测**：训练 + 推理指标实时可看（MLflow + Grafana）
7. **多企业落地**：X-user team 注册到 Keycloak 成为首个企业；所有资源（OSS 路径 / K8s ns / Gravitino schema / MLflow experiment）通过 enterprise_id 引用；用户 SDK 调用时由 Org Service 自动从 token 解析 enterprise_id
8. **Embedding 闭环**：批量生成向量 → Lance + IVF_PQ 索引 → ANN 查询可用
9. **架构标准**：grep 全部资源命名（OSS bucket prefix / K8s 资源 / Gravitino / MLflow），**任意 display_name（如 "x-user"）不得出现在资源标识中**
10. **Agent + 统一 LLM 接入（v2）**：经统一 LLM Gateway 用 Claude/Codex/Minimax（API key 计费）发起对话；内置 agent 能完成一次"数据探查 / 管线开发 / 模型开发"任务；LLM 调用按 enterprise/group 计量与授权
11. **Agentic Search（v3）**：一次自然语言查询经 agent 对多源多模态数据（OSS/Lance/Gravitino/MLflow）统一检索，返回带引用的综合结果，且结果严格限定在当前 enterprise/group scope

### 2.2 版本路线图（按交付优先级）

> **版本路线（2026-06-06 修订）**：**v1 = 数据域** → **v2 = Agent 开发平台 + 统一 LLM 接入** → **v3 = Agentic Search** → **v4 = 微调（SFT/LoRA）** → **v5 = 1B 预训练**。基础设施贯穿、随 v1 最先就位。**递增交付**（总 ~25 周，2026-06-06 → ≈2026-11-28，时间线见 §5）。
> **战略取向**：先用**第三方 LLM（Claude/Codex/Minimax，API key 按 token 计费）+ Agent** 快速交付应用价值；自研微调/预训练**后置**。
> **术语约定**：`v1`–`v5` **专指功能版本里程碑**；"以后再做"写 **`vN+`（未来/后续）**。大写 `V1`–`V12` 是验收标准 ID，与版本号无关。

**v1 基础设施（贯穿，最先就位）**

| 子系统 | 验收点 |
|---|---|
| **Keycloak(26.6.2) + Org Service** | OIDC token 校验 + 从 groups claim 解析 enterprise_id/group_id/role；Organizations + Group 子组 |
| **薄 can()（授权出入口）** | 认证 + **企业隔离硬检查**（`resource.enterprise_id == ctx.enterprise_id`）+ 基本角色门槛，in-code；`can()` 唯一出入口，无散落 `if enterprise_id == ...`（**细粒度授权 v2 上 Cerbos**） |
| **Audit Layer** | mutation + `/admin/*` 全有 audit；v1 追加写 OSS（事后尽力） |
| **Enterprise Provisioner** | `laictl --admin enterprise create` 建 Keycloak Organization + Group 骨架 + 资源前缀 |
| **API Gateway/BFF + API 契约** | gateway 路由 + token 校验；OpenAPI/proto 契约**先行**、入 git、CI 校验 breaking-change |
| **SDK + CLI** | 由 OpenAPI 契约生成 + 薄封装；submit_sft/deploy/workspace（自动注入 enterprise_id/group_id；submit_pretrain v5 接入） |
| 监控 | GPU/作业/IO 看板 |
| 数据存储 | OSS + Lance 就位 |
| ~~Quota Service~~（推迟）| v1 无 PG 预算账本；仅 Kueue 静态配额（Cohort=企业 / LocalQueue=组） |

**v1：数据管线 + 元数据 + 多模态数据处理（最高优先）**

| 子系统 | 验收点 |
|---|---|
| 数据管线 | 10TB 图文 → Data-Juicer 清洗 → Lance |
| 多模态数据处理 | 图文对齐 / 切分 / 过滤 / 去重，多模态特征落 Lance |
| 元数据 catalog | Gravitino 按 `e_xxx_g_yyy` / `e_xxx_shared` schema 注册 |
| 实验追踪 | MLflow experiment 按 enterprise_id/group_id tag 分组 |
| Embedding 服务 + 向量 | TEI/vLLM + Lance + IVF_PQ，ANN 查询可用 |
| Dev Workspace | code-server + Remote-SSH（按 enterprise/group 分配）；数据探索/处理用 |
| **前端（数据域，完整 UI）** | 数据集管理（上传/浏览/血缘）+ 数据管线提交/监控 + 元数据浏览 + 实验对比，**React + Vite**（ADR-019） |

**v2：Agent 开发平台 + 统一 LLM 接入 + 统一对话交互**

| 子系统 | 验收点 |
|---|---|
| **统一 LLM 接入服务（LLM Gateway，⑮）** | 统一 API（chat/completion/embedding）接 **Claude / Codex / Minimax API（按 token 计费）**；模型路由 + API key 管理 + 限流 + 按 enterprise/group 计量；**LiteLLM 待选型**（spike 选定，见 §6/ADR） |
| **Agent 平台 + 统一对话交互（⑯）** | Agent 框架 + 运行时 + **统一 chat UI**；内置 agent：**模型开发 / 管线开发 / 数据探查**（复用第三方模型 + 工具调用走 Platform API 契约） |
| **Cerbos PDP（授权升级）** | 细粒度 ABAC / derived role **替换薄 can()**，43 条 AC 全过；agent/LLM 访问数据/模型按 enterprise/group scope 受控；handler 零改（seam，ADR-011） |
| **前端（Agent/对话域）** | 统一对话界面 + agent 任务/会话管理 + LLM 用量/模型管理页 |

**v3：Agentic Search（多源多模态统一检索）**

| 子系统 | 验收点 |
|---|---|
| **Agentic Search agent（⑰）** | 一个 agent 对集成的**多源多模态数据**（OSS / Lance 向量 / Gravitino 元数据 / MLflow…）做**统一检索**：查询规划 → 多模态检索（结构化+向量+全文）→ 综合 → 带引用返回 |
| 检索编排 | 复用 v1 数据/向量 + v2 LLM Gateway；结果按 enterprise/group scope 过滤（数据层 + Cerbos） |
| **前端（搜索）** | 统一搜索入口 + 多模态结果展示 + 引用溯源 |

**v4：微调（SFT / LoRA）**

| 子系统 | 验收点 |
|---|---|
| 微调工作流 | 基于现成基座 LoRA/SFT 跑通，新模型版本登记 |
| Checkpoint + 容错 | 杀 pod 自动恢复，丢失进度 ≤ 1h |
| 推理服务（自托管） | 微调模型部署 HTTP（vLLM），有 P95 延迟基准；可经 LLM Gateway 统一暴露 |
| **前端（作业/模型）** | 微调提交/监控页 + 模型管理/部署页（提交 + 监控） |

**v5：1B 模型预训练**

| 子系统 | 验收点 |
|---|---|
| 训练运行时 | 8 卡 DDP 跑通 1B 多模态 baseline，3-4 天完成 |

**P2（贯穿，靠后）**：前端其余域（企业/成员/角色 admin 管理页——v1 可暂用 CLI/后台）、监控看板深化、CI（平台代码 + 镜像）。

### 2.3 v1 明确不做

- ❌ 多机分布式预训练（架构留口子）
- ❌ 推理 HPA / 灰度 / A/B / 多模型路由网关
- ❌ 自动 lineage 追踪（手工 Gravitino tag）
- ❌ 数据脱敏 / 隐私合规

> 注：v1 **必做**审计（Audit Layer，子系统 ⑭）—— 所有 mutation API、`/admin/*`、`--force` 和 admin override 强制写 `audit_log`；v1 不做的是"跨企业审计聚合视图 / tamper-proof 归档 / SIEM 集成"，留 vN+。
- ~~❌ Web UI 提交作业（CLI/SDK 即可）~~ → **已反转(ADR-019)**:owner 终态是 GUI,出口⑤ 改真 GUI(React/Vite 数据域控制台 + BFF),CLI 反而推迟为 ops 工具;数据域 Web UI 进 S1(Plan 8)
- ❌ Megatron / NeMo（v1 用 DDP/DeepSpeed）
- ❌ Ray Train（v1 训练不用 Ray，仅数据管线用 Ray Data）
- ❌ LanceDB（用开源 Lance + 自封装 VectorTable）
- ❌ 跨可用区/region 容灾
- ❌ Keycloak 高级特性：SAML、social login、自助注册、密码策略复杂规则（v1 单 realm + 公司 LDAP/AD 联邦或本地用户即可）
- ❌ 多企业 跨域共享数据（v1 严格隔离）

### 2.4 v1 之后的演进点（vN+）

| 现在留口子 | vN+ 补全 |
|---|---|
| Keycloak 单 realm + 一个企业 | 多企业 上线（仅在 Keycloak 加 group/role + Org Service 注册新 enterprise_id；**资源命名零改动**） |
| LocalQueue per enterprise/group 简单配额 | 真正的 quota engine（多维：GPU/CPU/storage/cost）+ 审计 |
| 单节点训练 | 多节点 FSDP/Megatron + Volcano gang + eRDMA |
| 单实例 vLLM | 多模型推理网关 + HPA + 金丝雀 |
| 手工 Gravitino tag | OpenLineage 自动血缘 |
| 训练镜像契约 | 加 train-megatron / train-ray 镜像 |

### 2.5 X-user Team（首个企业）配合契约

- 提供 1B baseline 模型代码 + tokenizer
- 提供 SFT 数据样本（小集合先跑通，再上量）
- 数据上传到约定 OSS 路径（路径由平台分配的 `enterprise_id` 决定）+ 提供 schema
- 推理接口的 I/O 契约
- 注册成员到 Keycloak（首批 N 人）

---

## 3. 技术架构与选型

### 3.0 语言栈、微服务架构与 API 优先契约

> ⚠️ **2026-06-04 调整**：后端改为**微服务架构（按子系统全拆）** + **API 优先**；前端为**完整页面（数据域优先）**。原"控制面同事务单体"（依赖 audit/quota 同 PG 事务）的硬约束，已随 **PG/Quota/同事务审计推迟**（ADR-010）而**解除**——各服务独立部署、不共享 DB session。

#### 3.0.1 微服务分解（按子系统全拆）

| 服务 | 职责 | 语言/栈 |
|---|---|---|
| **api-gateway / BFF** | 前端/SDK/CLI 入口、路由、token 校验、聚合；**OIDC 会话终结**（登录/会话/登出,无状态加密 cookie,ADR-019）+ serve 前端 dist | Python FastAPI（或 Envoy + 薄 BFF） |
<!-- 06-13:反代分两层。内层 gateway(BFF)用**应用内 httpx 反代**(`services/_scaffold/proxy.py`)——因转发前后要做 JWKS 验签/审计/Context 注入,属 Python 应用逻辑,不用 nginx。外层 L7 LB(TLS 终止/负载均衡/静态限流)用阿里云 ALB/SLB,摆在 gateway 前面,S2a 引入。两层职责不同、不冲突:`客户端 → ALB → gateway(BFF 应用内反代) → 下游服务`。 -->
| **identity-org-service** | Keycloak-facing：Organization/Group/成员；解析 groups claim | Python FastAPI |
| **authz (Cerbos)** | PDP，策略 in git（ADR-011） | Cerbos（Go，sidecar/服务） |
| **data-pipeline-service** | 数据管线 + 多模态处理（Ray Data / Data-Juicer / Argo 编排） | Python |
| **metadata-service** | Gravitino catalog + MLflow 实验 | Python |
| **training-service** | 训练 / 微调作业（Volcano / Kueue） | Python |
| **inference-service** | 部署 vLLM / TEI | Python |
| **workspace-service** | code-server / SSH（K8s operator） | Go (controller-runtime) |
| **provisioner** | 企业/组 reconcile（Keycloak Org/Group + 资源） | Go (controller-runtime) |
| _(推迟)_ quota-service / billing | 预算账本（待 PG 回归） | — |

各服务独立部署/扩缩，统一在 **api-gateway** 后；服务间与对外通信都走 **API 优先契约**。

#### 3.0.2 API 优先（API-first）

1. **契约先行**：每个服务先定 **OpenAPI 3.1**（对外 / BFF）或 **protobuf/gRPC**（内部高频）契约，再生成 server stub + client；**禁止手写客户端**。
2. **契约入 git、版本化、CI 校验** breaking-change（如 `oasdiff` / `buf breaking`）。
3. **前端、SDK、CLI、服务间 client 全部由契约生成**，杜绝漂移。
4. **鉴权统一**在 gateway（token 校验）+ Cerbos（授权），各服务不重复实现。

#### 3.0.3 语言分层

| 类别 | 语言 | 理由 |
|---|---|---|
| 控制面 + 数据/训练/推理服务 | **Python 3.12**（FastAPI；**uv 管理**，`.python-version` + `uv.lock`） | 团队主语言；ML 生态原生；OpenAPI 友好 |
| K8s controller（provisioner / workspace） | **Go**（controller-runtime / kubebuilder） | K8s 生态标准 |
| 授权 PDP | **Cerbos**（Go，不自写） | ADR-011 |
| **前端** | **TypeScript + React + Vite**（ADR-019;原拟 Next.js,改 Vite SPA 由 gateway serve dist 求同源） | 数据域控制台;OIDC 经 BFF（前端不持 token） |
| SDK / CLI | **Python**（由 OpenAPI 生成 + 薄封装） | v1 用户全 Python |
| 训练/推理/数据管线镜像 | Python + bash | PyTorch / Ray / Data-Juicer / vLLM / TEI 原生 |

约束：新增语言走 ADR；跨语言 SDK 必须由 OpenAPI 生成。

#### 3.0.4 仓库组织（monorepo，按服务分包）

> **命名口径(2026-06-13 修正)**:Python 包名不能含连字符,故服务目录用**下划线 + `_service` 后缀**(如 `services/identity_org_service/`);对外契约名/URL 仍可用连字符(如 `contracts/openapi/identity-org.yaml`)。`✅/⏳` 标实际状态,`(Plan N / vX)` 标建于哪一步。

```
lite-ai-infra/
├── contracts/                      # ✅ API 优先：OpenAPI 契约（真相源，先于实现）
│   └── openapi/identity-org.yaml   # ✅ identity-org 契约
├── services/                       # 各服务：契约 → 生成模型 → FastAPI app(/docs) → 实现
│   ├── gateway/                    # ✅ BFF / API Gateway（token 校验 + 路由 + 聚合；⏳ OIDC 会话终结 gateway/bff/ + serve dist，ADR-019）
│   ├── identity_org_service/       # ✅ Plan 3（/v1/me/orgs 从 gateway 迁出，独立）
│   ├── data_pipeline_service/      # ✅ Plan 5（包 pipelines/data_prep；异步作业薄壳）
│   ├── metadata_service/           # ✅ Plan 4（Gravitino 后端）
│   ├── llm_gateway_service/        # ⏳ v2：统一 LLM 接入（LiteLLM 待选型）
│   ├── agent_platform_service/     # ⏳ v2：Agent 框架/运行时 + 统一对话后端
│   ├── agentic_search_service/     # ⏳ v3：多源多模态统一检索 agent
│   ├── training_service/           # ⏳ v4 微调 / v5 1B
│   ├── inference_service/          # ⏳ v4
│   ├── workspace/                  # ⏳ S2c：Go operator（非 Python，无 _service 后缀）
│   └── provisioner/                # ⏳ S2c：Go controller（同上）
├── pipelines/                      # ✅ 实现层：批处理逻辑（服务背后；非常驻服务）
│   └── data_prep/                  # ✅ tar→DJ/Ray→Lance（data_pipeline_service 的内部实现）
├── libs/                           # ✅ 共享层：identity / authz / audit / contracts_gen
├── authz/                          # ⏳ v2：Cerbos 策略（YAML, in git；现暂存 spikes/cerbos_seam/）
├── frontend/                       # ⏳ S1 Plan 8(ADR-019 提前)：React + Vite 数据域控制台（gateway serve dist;含上传页消费 Plan 7 契约）
├── sdk/  cli/                      # ⏸ 推迟为 ops 工具（ADR-019;原 Plan 6 laictl 文档已删,日后重写）。上传后端=data_pipeline_service(Plan 7 ✅ presigned 直传,ADR-020)
├── deploy/                         # ✅ dev compose + test IaC（Helm/ArgoCD → S2a）
│   ├── dev/                        # ✅ docker-compose（Keycloak + MinIO）
│   └── test/                       # ✅ 阿里云测试环境 IaC（ECS compose + terraform）
├── spikes/                         # ✅ spike harness（lance_oss / datajuicer_ray / cerbos_seam / keycloak_org）
├── scripts/  tests/                # ✅ CI 护栏脚本 / 两层测试
└── docs/                           # ✅ specs / adr / plans / ops / user-stories
```

> **分层纪律(import-linter 强制)**:`services → pipelines → libs` 单向;`libs`/`pipelines` 不得反向 import `services`。`pipelines`/`libs` 是 §3.0.1 服务表之外的**实现层**——服务是部署/契约单位,实现层是它们的共享内部代码(2026-06-13 补;原 spec 只画到服务颗粒度)。

**关键**：各服务**独立可部署**；服务间只通过 `contracts/`（生成的 client）调用，**不共享 DB session**。数据一致性见 **ADR-013**：**v1 外部副作用走 reconcile**（声明式，无需 PG 事务）；PG 回归后单服务内 outbox + 跨服务 saga（**非分布式同事务**）。禁止把 Kueue/Argo/Volcano/Gravitino/OSS 调用纳入同步链路阻塞主流程。

#### 3.0.5 演进口径

- **v1 无 PG**；预算/审计 PG 回归时，新增 **quota-service** 为独立服务（per-service DB；跨服务一致性走 saga，ADR-013）。
- 服务粒度可随负载再调整；**契约稳定则内部重构对其他服务无影响**（API 优先的核心收益）。
- 3 人团队下的纪律：服务虽全拆，但**共享统一的脚手架**（同一 FastAPI 模板 / 同一 CI / 同一可观测埋点），避免每个服务各搞一套。

### 3.1 完整组件清单

| 类别 | 组件 | 版本 | 部署形态 |
|---|---|---|---|
| **底座** | 阿里云 ACK | Pro 1.30+ | 托管 K8s |
| | 阿里云 OSS | — | 标准存储 + 归档 |
| | ACR | — | 镜像仓库 |
| | RDS PostgreSQL | 16 | 托管，给 MLflow + Gravitino + Keycloak + Platform API |
| **身份/企业** | **Keycloak** | **26.6.2** | **StatefulSet（HA 2 副本）+ RDS PG 主备** |
| | **Org Service** | **自研** | **Platform API 内置模块** |
| **调度** | Volcano | v1.9+ | gang scheduling |
| | Kueue | v0.7+ | 队列 + 配额（按 企业） |
| | Argo Workflows | v3.5+ | 数据管线 DAG |
| | KubeRay Operator | latest | RayCluster on demand |
| **训练 / 微调** | PyTorch | 2.4+ | 镜像内 |
| | DeepSpeed | 0.15+ | 镜像内（备选模板） |
| | accelerate / peft | 最新 | 镜像内 |
| | 训练镜像契约 | 自研 | 定义入口/环境变量/信号 |
| **推理** | vLLM | 0.6+ | K8s Deployment |
| | TEI | 1.5+ | K8s Deployment（embedding） |
| **数据** | Ray | 2.35+ | KubeRay Operator |
| | Data-Juicer | 1.0+ | Ray on demand |
| | Lance（pylance） | 0.18+ | 嵌入式库（数据格式 + 向量） |
| | VectorTable 抽象 | 自研 | 封装 Lance 向量 API |
| **元数据** | Apache Gravitino | 0.6+ | StatefulSet **2 副本（active-active，后端 RDS PG 提供一致性）+ Service VIP**；详见 §3.16.2 |
| | MLflow | 2.16+ | Deployment（experiment 按 enterprise_id tag） |
| **观测** | Prometheus | 2.54+ | kube-prometheus-stack |
| | Grafana | 11+ | 同上（OIDC 接 Keycloak） |
| | DCGM Exporter | 3.3+ | DaemonSet |
| | OpenSearch | 2.x | StatefulSet **3 节点 cluster（master+data 合并，replica=1）** + 本地 PV，14 天保留；**v1 启用 security plugin（per enterprise/group role + index pattern ACL）+ ILM（per enterprise/group index 大小/天数上限）**；冷归档 oss://logs/{enterprise_id}/；详见 §3.16.1 |
| | Fluent Bit | 3.x | DaemonSet，按 K8s namespace 注入 `enterprise_id` label |
| **平台自身** | Platform API | 自研 | FastAPI（Python 3.12，uv 管理，Keycloak token 校验中间件） |
| | SDK | 自研 | Python pkg（自动注入 token + enterprise_id 解析） |
| | CLI（laictl） | 自研 | Python click（首次用 `laictl login` 走 OIDC device flow） |
| | Portal | 自研 | **React + Vite**（ADR-019;OIDC 经 BFF,前端不持 token） |
| | Workspace Operator | 自研 | controller-runtime |
| **Workspace** | code-server | 4.92+ | dev 镜像内 |
| | OpenSSH | — | dev 镜像内 |

### 3.2 企业模型（核心）

> ⚠️ **本节已由 [ADR-010](../../adr/ADR-010-multi-enterprise-tenancy-model.md)（多企业企业模型）与 [ADR-011](../../adr/ADR-011-authorization-pdp-cerbos.md)（Cerbos PDP）修订。** 当前权威模型：
> - **层级**：平台 → 企业 → 用户组 → 用户；标识符 `enterprise_id`(e-XXXX, 全局唯一) + `group_id`(g-XXXX, 企业内唯一)。
> - **身份+组织+成员+角色全在 Keycloak**（单一 realm，**26.6.2**）：企业=**Organization**；用户组+角色=**Group 子组** `/e-x/g-y/{admins|members}`，随 token 的 `groups` claim 带出（无歧义携带 企业/组/角色）；用户=**User**。**v1 一个用户只属一个企业**（不跨企业；模型不排斥未来扩展）。
> - **授权**：**Cerbos** 做 PDP（ABAC/ReBAC，derived role = 带 scope 的角色），Platform API 做 PEP/PIP，`PolicyEngine.can()` 唯一出入口。**principal 来自 token 的 `groups` 解析**；**resource 属性来自资源自身**（OSS 路径 / K8s label / MLflow tag / Gravitino schema 名）。**OSS 等数据路径**由 Cerbos 决策 + 阿里云 RAM/STS 受限凭据执行。
> - **审计（v1 必做）**：只追加写 OSS（`oss://audit/...`）+ Cerbos decision log（可选 OpenSearch 索引）；**事后尽力写，非同事务原子**（强保证待 PG 回归）。
> - **v1 推迟（需要时引入 PG）**：两级预算/配额账本、中央资源元数据目录、同事务原子审计。**v1 无 PG。**
> - **术语已全面对齐两级模型**（2026-06-07 清扫）：个别插图/示例为**企业级**简写，**用户组细分以 §3.2 标识符 / §3.3 / §3.4 / AC 表为权威**；预算 / Quota / 中央元数据 PG / Enterprise Provisioner 的 PG 部分在 v1 **推迟（vN+）**。

#### 标识符规范

```
enterprise_id：e-XXXX   (如 e-0001，全局唯一)
group_id：      g-XXXX   (如 g-0001，企业内唯一)

  • OSS / K8s 路径：        .../e-0001/g-0001/...   (企业共享: .../e-0001/shared/...)
  • Gravitino schema：      e_0001_g_0001  (私有) / e_0001_shared  (共享，下划线 SQL 兼容)
  • MLflow tag：            enterprise_id=e-0001, group_id=g-0001
  • Keycloak Organization： org = 企业 (e-0001)
  • Keycloak Group 子组：   /e-0001/g-0001/admins | /e-0001/g-0001/members  (编码 组+角色，进 token)
  • display_name：          "X-user"  (Keycloak Organization/Group attribute，绝不进资源名)

首个客户 = enterprise_id "e-0001"，其下用户组 g-0001…；display_name "X-user"
```

> **as-built 修订(ADR-016/023/024)**:上表中**数据集相关**两项已变更——
> ① **数据集 OSS 路径**按 owner:`.../e-0001/{user}/{raw,processed}/...`(不再 `.../e-0001/g-0001/...`;ADR-024)。② **Gravitino**:metalake `e_XXXX` / catalog `data` / schema `datasets`,每数据集 = fileset(不再 `e_0001_g_0001` schema;ADR-016)。
> 其余项(K8s/Kueue 路径与命名空间、MLflow tag、Keycloak Org/Group 子组、display_name)**不变**——group 仍是访问/计算/组织维度。**非数据集资源**(Workspace/作业/推理)的 group 路径属未建愿景,按本表愿景值理解。

#### 组织 / 成员 API（Platform API 薄层封装 Keycloak Admin API）

```python
# 身份/组织/成员/角色的真相源 = Keycloak（Organizations + Group 子组）
# Platform API 仅做封装 + 鉴权（Cerbos）；SDK 不传 enterprise_id/group_id，从 token 的 groups claim 解析

# routers/v1/  普通业务
GET  /v1/me/orgs                              # 从 token groups 解析：我属于哪个企业/组/角色
POST /v1/orgs/{eid}/groups/{gid}/members      # enterprise-admin 加/移成员（→ Keycloak Admin API）
GET  /v1/datasets/{uri}/refs                  # 数据集引用列表（驱动 delete 决策 + --dry-run，§3.12）
GET  /v1/audit                                # 本企业 audit（enterprise-admin；v1 读 OSS 审计）

# routers/admin/  (X-Admin-Path: true header；仅 platform-admin role)
POST   /admin/enterprises                     # 开通企业（建 Keycloak Organization + 用户组骨架，§3.14）
PATCH  /admin/enterprises/{eid}               # suspend / archive 状态变更
GET    /admin/audit?enterprise_id=*           # 跨企业 audit 查询
POST   /admin/datasets/{uri}:gc               # 孤儿数据集 gc（强 audit + reason 必填）
POST   /admin/pipelines/{id}:cancel           # 跨企业救火（reason 必填）

# v1 推迟：/quota 配额相关 API（预算账本未做，见 §3.10）
```

#### Keycloak 设计（v1，26.6.2，单 realm + Organizations）

```
Realm: lite-ai-infra        (单一 realm，只管认证)
  Organizations:
    • e-0001                (企业=客户；attr: display_name；可挂 per-企业 IdP/域名，SSO 用)
  Clients:
    • platform-api      (confidential, server-side token validation)
    • cli               (public, device-code flow)
    • portal            (public, authorization code + PKCE)
    • workspace-ingress (confidential, OIDC proxy)
    • grafana / mlflow  (confidential, OIDC integration)
  Groups (用户组 + 角色，子组路径编码，进 token 的 groups claim):
    • /platform-admins              (平台超管，跨企业)
    • /e-0001/g-0001/admins         (企业 e-0001 / 用户组 g-0001 / 角色 admin)
    • /e-0001/g-0001/members
    • /e-0001/g-0002/members
  User Federation: 公司 LDAP/AD 或本地用户；各企业自带 IdP 经 Organization 挂（未来）
```

> 角色**不用** Keycloak realm role（扁平无作用域），用**子组路径编码**，随 token 带出，PEP 解析 `(企业, 组, 角色)`；判权由 **Cerbos**（ADR-011）。**v1 一个用户只属一个企业。**

#### 多企业资源全景图

```
                  ┌────────── 企业 Enterprise (e-0001) ──────────┐
                  │                                               │
 身份层           │  Keycloak Organization: e-0001               │
 (Identity)       │   └─ Group 子组: /e-0001/g-0001/{admins,     │
                  │       members}（用户组+角色，进 token）       │
                  │                                               │
 配额层           │  Capsule Tenant CR: e-0001                    │
 (Quota)          │   ├─ Namespace 列表: e-0001-g-0001-{用途}     │
                  │   ├─ ResourceQuota: GPU / CPU / Mem           │
                  │   ├─ NetworkPolicy                            │
                  │   └─ RBAC RoleBinding                         │
                  │                                               │
 存储层           │  OSS Prefix: oss://lite-ai-infra/.../e-0001/  │
 (Storage)        │   ├─ raw / processed / embeddings             │
                  │   ├─ checkpoints / models                     │
                  │   └─ logs (冷归档自 OpenSearch)               │
                  │                                               │
 元数据层         │  Gravitino Schema: e_0001                     │
 (Metadata)       │   ├─ Catalog 资产注册                         │
                  │  MLflow Experiments (tag: enterprise_id=e-0001)   │
                  │  PG: enterprise_metadata 行级隔离                 │
                  │                                               │
 工作负载层       │  K8s Workloads（装在 企业 ns 里）           │
 (Workload)       │   ├─ Volcano Job (训练)                       │
                  │   ├─ Deployment (vLLM / TEI 推理)             │
                  │   ├─ Workspace Pod (code-server)              │
                  │   ├─ Argo Workflow / Ray Cluster              │
                  │                                               │
 调度层           │  Kueue LocalQueue: e-0001-g-0001-queue        │
 (Scheduling)     │                                               │
 网关层           │  Ingress Hosts: *.e-0001.lite-ai.local        │
 (Networking)     │                                               │
 观测层           │  OpenSearch Index: logs-e-0001-*              │
 (Observability)  │  Grafana Org / Datasource: e-0001             │
                  │  Prometheus labels: enterprise_id=e-0001          │
                  │                                               │
 凭证层           │  Vault / KMS: secret/enterprises/e-0001/  (vN+)    │
 (Secrets)        │  v1 走 OSS RAM 子账号 + env var               │
                  │                                               │
 审计层           │  Audit Log: audit_log（按 enterprise_id）  │
 (Audit)          │                                               │
                  └───────────────────────────────────────────────┘
```

#### 完整资源清单（v1 必管 + vN+ 演进）

| # | 资源类型 | 系统 | 命名规则 | 创建时机 | v1 / vN+ |
|---|---|---|---|---|---|
| 1 | 企业元数据记录 | PG | `enterprise_metadata` 表，pk = `enterprise_id` | 企业创建 | v1 |
| 2 | Group | Keycloak | `/e-{enterprise_id}/g-{group_id}/{admins|members}` | 企业创建 | v1 |
| 3 | Role | Keycloak | `group-admin` / `member`（realm 级） | 一次性 | v1 |
| 4 | Capsule Tenant CR | K8s | name = `enterprise_id` | 企业创建 | v1 |
| 5 | Namespace | K8s | `{enterprise_id}-{group_id}` 或 `{enterprise_id}-{group_id}-{用途}` | 按需，Capsule 托管 | v1 |
| 6 | ResourceQuota | K8s | Capsule 自动下发 | 跟随 Tenant CR | v1 |
| 7 | NetworkPolicy | K8s | Capsule 自动下发 | 跟随 Tenant CR | v1 |
| 8 | RBAC RoleBinding | K8s | Capsule 自动下发 | 跟随 Tenant CR | v1 |
| 9 | Kueue LocalQueue | K8s | `{enterprise_id}-{group_id}-queue` | 企业创建 | v1 |
| 10 | OSS Prefix | OSS | `oss://lite-ai-infra/.../{enterprise_id}/` | 企业创建 | v1 |
| 11 | OSS RAM 子账号 / STS Role | RAM | `lite-ai-{enterprise_id}` | 企业创建 | v1 |
| 12 | Gravitino Schema | Gravitino | `t_{enterprise_id_underscored}`（如 `e_0001`） | 企业创建 | v1 |
| 13 | MLflow Experiment | MLflow | tag `enterprise_id={enterprise_id}` | 用户首次创建 run 时 | v1 |
| 14 | OpenSearch Index Pattern | OpenSearch | `logs-{enterprise_id}-*` | Fluent Bit 自动 | v1 |
| 15 | Grafana Datasource / Org | Grafana | per enterprise/group datasource | 企业创建 | v1 |
| 16 | Ingress Host | K8s Ingress | `*.{enterprise_id}.lite-ai.local` | 部署推理 / Workspace 时 | v1 |
| 17 | TLS Cert（per enterprise/group 子域） | cert-manager | wildcard 或 per-host 自动签发 | 跟随 Ingress | v1 |
| 18 | 训练 Job | Volcano | `train-{enterprise_id}-{run_id}` | 用户提交 | v1 |
| 19 | 推理 Deployment | K8s | `inf-{enterprise_id}-{model}-{ver}` | 用户部署 | v1 |
| 20 | Workspace Pod | K8s | `ws-{enterprise_id}-{user}` | 用户起 | v1 |
| 21 | Argo Workflow | K8s | `flow-{enterprise_id}-{job}` | 数据管线触发 | v1 |
| 22 | Audit Log 记录 | PG / OpenSearch | per enterprise/group table 或 index，含 `enterprise_id` 列 | 每次操作 | v1（业务侧自记录）/ vN+ 强化 |
| 23 | Vault / KMS Secret Path | Vault | `secret/enterprises/{enterprise_id}/*` | 企业创建 | vN+ |
| 24 | Cost Center / Billing | 自研 | per enterprise/group cost ledger | — | vN+ |

> 标识符规则统一遵循上文"标识符规范"小节；`display_name` 严禁出现在任何资源名 / 路径 / schema / index 中（v1 验收硬约束第 9 条）。

#### 隔离强度矩阵

| 隔离维度 | v1 强度 | 实现机制 | vN+ 加强 |
|---|---|---|---|
| 计算（K8s） | **强** | namespace + Capsule 强制 NetworkPolicy + ResourceQuota + RBAC | — |
| 存储（OSS） | **中-强** | RAM 子账号 + 路径 prefix + bucket policy（每企业 一个 RAM 子账号） | — |
| 元数据（Gravitino） | **中** | per enterprise/group schema + schema 级 ACL | RBAC 加强 |
| 实验（MLflow） | **弱** | tag 软隔离 + Org Service 中间件硬过滤 | 接 OSS 版 RBAC 或迁 commercial |
| 日志（OpenSearch） | **强（v1 起）** | OpenSearch security plugin（per enterprise/group role + `logs-{enterprise_id}-*` / `audit-{enterprise_id}-*` index ACL）+ Grafana datasource filter | 跨集群联邦查询 |
| 网络（Ingress） | **强** | per enterprise/group 子域 + OIDC 鉴权 | — |
| 凭证 | **弱** | env var + OSS RAM 子账号（共享存储位置） | Vault per enterprise/group path（vN+ 落地） |
| 监控指标 | **中** | Prometheus label `enterprise_id` + Grafana org | — |
| 审计日志 | **中（v1）** | **v1：OSS 追加写（事后尽力，非同事务原子，ADR-010/013）** + 可选 OpenSearch 索引；~~PG 同事务权威~~ → **vN+（PG 回归）** | 同事务原子审计 + tamper-proof（WORM）+ SIEM |
| 调度（Kueue） | **强** | per enterprise/group LocalQueue + ClusterQueue 配额借用规则 | — |

#### 多企业机制硬纪律（写进 constitution）

> 已由 [ADR-010 附录 A](../../adr/ADR-010-multi-enterprise-tenancy-model.md) 修订为多企业两级模型（`enterprise_id` + `group_id`，身份/角色全在 Keycloak、v1 无 PG）：

1. **`EnterpriseId` / `GroupId` 是独立类型**（Types 层），不与 string 互转；构造任何资源标识符的函数签名只接收对应类型
2. **资源命名必须含 `enterprise_id`**（私有资源还须 `group_id`）；`display_name` 严禁出现在资源名 / 路径 / schema / index / label
3. **JWT 仅作认证 + 携带组路径**；`(企业, 组, 角色)` 由 token 的 `groups` claim（`/e-x/g-y/{admins|members}`）解析；handler 不允许从 query/body 直接读 `enterprise_id`/`group_id`
4. **每次访问决策必须经过 `PolicyEngine.can(ctx, action, resource)`**（内部调 Cerbos，ADR-011），禁止散落 `if enterprise_id == ...` 判断
5. **硬隔离不变式**：非 admin 路径必须 `resource.enterprise_id == ctx.enterprise_id`；私有资源还须 `group_id` 匹配或 `enterprise-admin`；跨企业仅 `platform-admin` 走显式特权 API
6. **资源归属编码在资源自身**（OSS 路径 / K8s label / MLflow tag / Gravitino schema），Cerbos 的 resource 属性据此读取（v1 无中央元数据 PG）
7. **CI 防线**：import-linter 检查依赖方向 + grep 检查 `display_name` 泄漏到资源命名 + grep 散落的 `enterprise_id/group_id` 比较
8. **数据路径系统（OSS）不靠 PDP 内联执行**：Cerbos 只决策"发不发受限凭据"，阿里云 RAM/STS 在数据路径做路径级执行

### 3.3 命名空间规划（按 enterprise_id / group_id）

```
ack-cluster/
  ├─ platform-system/         # 平台组件（API、Portal、MLflow、Gravitino、Keycloak、监控、Cerbos）
  ├─ kueue-system/
  ├─ volcano-system/
  ├─ argo/
  ├─ ray-system/
  ├─ e-0001-g-0001/           # 企业 e-0001 / 用户组 g-0001 的作业、推理、Workspace
  └─ e-XXXX-g-YYYY/           # 其他企业/组
```
> namespace 命名 `{enterprise_id}-{group_id}`；workload 带 label `enterprise_id` / `group_id`（供 Cerbos 读 + 数据层过滤）。

### 3.4 OSS 路径约定（按 enterprise_id / group_id）

```
oss://lite-ai-infra/
  ├─ raw/<eid>/<gid>/<dataset>/...           # 用户组私有
  ├─ processed/<eid>/<gid>/<dataset>.lance/
  ├─ embeddings/<eid>/<gid>/<dataset>.lance/
  ├─ checkpoints/<eid>/<gid>/<run_id>/
  ├─ models/<eid>/<gid>/<model>/<version>/
  ├─ shared/<eid>/...                         # 企业共享（公共数据集/基座模型）
  ├─ logs/<eid>/<gid>/<run_id>/
  └─ audit/<yyyy>/<mm>/<dd>/*.jsonl           # 平台审计（§3.11）
```

**访问控制**：客户端直连 OSS 不经 API，故由 **Cerbos 决策 + 阿里云 STS 短期凭据**（policy 限定到 `e-0001/g-0001/*` 或 `e-0001/shared/*` 前缀）执行；详见 §3.13 / ADR-011。

### 3.5 资产 URI（用户视角）

```
统一 URI 协议：gravitino://<scope_or_alias>.<name>[@<version>]

用户两种用法：
  • 别名 "my"：     gravitino://my/v1        ← SDK 自动替换为当前 enterprise_id/group_id（私有）
  • 别名 "shared"： gravitino://shared/base  ← 企业共享资产

底层 OSS 路径由 Platform API 通过 Gravitino 解析；归属（enterprise_id/group_id）来自 token 的 groups claim。
用户从不直接拼 OSS 路径或 enterprise_id/group_id 字符串。
```

### 3.6 训练镜像契约

```
契约：
  • 入口：/opt/train/entrypoint.sh
  • 必接环境变量：
      DATA_URI, OUTPUT_URI, MLFLOW_TRACKING_URI, MLFLOW_RUN_ID,
      CKPT_URI, RANK, WORLD_SIZE, ENTERPRISE_ID/GROUP_ID
  • 必输出：MLflow metrics + OSS checkpoints
  • 必接信号：SIGTERM 优雅保存

v1 官方镜像：
  • lite-ai-infra/train-pytorch-ddp:v1
  • lite-ai-infra/train-deepspeed:v1
  • lite-ai-infra/serve-vllm:v1
  • lite-ai-infra/serve-tei:v1
  • lite-ai-infra/dev-py311-cu124:v1
```

### 3.7 元数据职责划分（Gravitino vs MLflow）

- **Gravitino**：数据集 / 模型 / 部署的资产目录，**schema = enterprise_id**
- **MLflow**：单次训练的参数/指标/artifact，**experiment 按 enterprise_id 分组**
- **衔接**：MLflow 注册的 model artifact URI 反向登记到 Gravitino

### 3.7.1 KubeRay 使用边界（防蔓延契约）

KubeRay 在 v1 **只承载 Data-Juicer 工作负载**（10TB 数据清洗），不扩散到其它批处理：

| 工作负载 | v1 调度方式 |
|---|---|
| Data-Juicer 数据清洗 | **KubeRay**（Argo Workflow 拉起 RayCluster → 跑完即销毁，autoscaler 关闭） |
| Embedding 批量生成（TEI/vLLM 离线） | Argo + 普通 K8s Job |
| Lance 重打包 / 索引重建 | Argo + 普通 K8s Job |
| 通用 ETL / 统计 / 评估 | Argo + 普通 K8s Job |
| 训练 / SFT | Volcano（见 ADR-009） |

**理由**：
- Data-Juicer 是 Ray-native，原生算子并行 + 分布式 dedup；用普通 K8s Job 替代要自己重写一遍调度（成本 > 维护一个 operator）。
- 其它批处理用 Ray 不会带来不可替代收益，反而把 Ray object store / placement group / actor 故障语义负担引入运维。
- 一旦扩散，KubeRay 就会从"按需拉起的临时 cluster"变成"常驻多企业共享集群"，运维成本指数级上升。

**新增 Ray 用例必须走 ADR 评审流程**（写明"为什么 Argo + K8s Job 不够"）。这条契约由 PR review 把关——PR 引入新的 `RayCluster` / `RayJob` CRD 使用必须附 ADR 引用。

### 3.8 Workspace 形态

```
Workspace Pod = StatefulSet（保 PVC）
  ├─ code-server (port 8080)        浏览器 VSCode（OIDC 鉴权 by Keycloak）
  ├─ sshd (port 22)                  本地 VSCode Remote-SSH（key-pair 入 Keycloak attr）
  ├─ ~/workspace                     PVC 持久化
  ├─ /mnt/oss/<enterprise_id>/           OSS 通过 ossfs/JindoFS 挂载（仅本企业）
  └─ 预装：Python 3.12, uv, Git, 平台 SDK, PyTorch, Ray, Lance

生命周期：
  • 默认 0 GPU；按需 1 GPU（Kueue 配额限制单用户 ≤1）
  • 8h 空闲自动 stop（PVC 保留）
  • 用户重新 start 即可恢复

访问：
  • https://workspace.lite-ai-infra.internal/<workspace-id>/    (Keycloak OIDC)
  • ssh -p <NodePort> user@<workspace-id>.lite-ai-infra.internal
```

**v1 owner 限制**：Workspace 仅 `owner` 可进（含 SSH）；group-admin 不进队友 Workspace（user-stories §角色 2 决策）。platform-admin 经 `/admin/*` 可进任何 Workspace（救火，audit 必写）。

### 3.9 PolicyEngine（访问决策）→ Cerbos PDP

> **PDP 由 [ADR-011](../../adr/ADR-011-authorization-pdp-cerbos.md) 定为 Cerbos**（取代 ADR-007 自研）。`PolicyEngine.can()` 仍是唯一出入口（seam），内部调 Cerbos；本节列接口契约与调用链位置。

```python
# Platform API 内部接口（PEP）；内部调 Cerbos（PDP）
PolicyEngine.can(
    ctx: Context,        # PEP 从 token 的 groups claim 解析：user / enterprise_id / group_ids / role
    action: str,         # 如 "job.cancel", "dataset.delete", "train.submit"
    resource: Resource,  # enterprise_id / group_id / scope / owner / state（v1 从资源自身读，§3.2 硬纪律6）
) -> Decision            # allow / deny + reason
# PIP：principal 来自 token；resource 属性来自资源自身（OSS 路径/K8s label/MLflow tag/Gravitino schema）
```

**调用位置**：所有 mutation API + 跨资源读 API 都必须在 handler 入口调一次；通过后再走业务逻辑。普通业务路径下 `ctx.enterprise_id != resource.enterprise_id` 直接 deny（即便 platform-admin，普通路径仍按企业隔离）；私有资源还须 `group_id` 匹配或 `enterprise-admin`。

**v1 必须覆盖的决策维度**（与 user-stories AC 1:1 对应）：

> 下表术语映射到最终模型：`enterprise_id`→`enterprise_id`；`group-admin`→`enterprise-admin`；多出一层"用户组 scope"（私有资源须 `group_id` 匹配，`group-admin` 管本组）。所有规则在 Cerbos 策略中以 resource policy + derived role 表达。

| 维度 | 例 | AC 引用 |
|---|---|---|
| 企业边界 | `resource.enterprise_id == ctx.enterprise_id` | AC-6 / AC-8 / AC-13 / AC-15 / AC-26 |
| Owner 检查 | mutation 默认 `resource.owner == ctx.user` | AC-2 / AC-24 / AC-25 / AC-31 |
| 角色门槛 | `train.submit + gpu>4` 需要 `group-admin` | AC-5 / AC-10 |
| 状态约束 | `job.delete` 拒 completed；`pipeline.update` 拒 running | AC-3 / AC-30 |
| 派生属性（delete） | `dataset.delete`：`ref_count == 0` 才允许直接删；`ref_count > 0` 时普通成员拒 | AC-22 / AC-23 |
| 派生属性（deprecate） | `dataset.deprecate`（`--force`）：owner 或 group-admin 均可；**不跳 ref_count**；结果是 `deprecated` 状态（OSS 保留，阻止新引用）而非立即删除；ref_count 降为 0 后才真正删除 | AC-27 |
| 特权路径 | `/admin/*` 仅 `platform-admin` | AC-14 / AC-16 / AC-17 / AC-34 |
| Pipeline update 所有权 | `pipeline.update params` 仅 pending 状态；普通成员仅限 `resource.owner == ctx.user`；group-admin 可改任意成员的 pending 管线 | AC-35（新） |
| Workspace 入口 | `workspace.enter` 仅 `resource.owner == ctx.user`；group-admin 在 v1 被显式拒（非 owner 无法入）；platform-admin 仅走 `/admin/*` 可进 | AC-36（新） |

**实现约束**：
- Cerbos 无状态、策略 in git 可单测；`can()` 输入只有 ctx + action + resource snapshot
- 决策结果必须**可解释**（`reason` 字符串直接进 4xx 响应 body 和 audit log）
- handler 禁止散落 `if enterprise_id ==`（CI grep 拦截，硬纪律第 4 条）
- **resource 属性来源做成抽象**：v1 从资源自身读，PG 回归后改从 PG 读，handler 不变

### 3.10 Quota Service（提交时配额预检）

> ⚠️ **v1 推迟（ADR-010）**：两级预算/配额账本依赖 PG，v1 不建 PG，故 **Quota Service 推迟**——v1 无 submit-time 预算预检与多维滚动账本。v1 仅靠 **Kueue 静态配额**（Cohort=企业 / LocalQueue=用户组）做 admit-time 限制。下文为 PG 回归后的完整设计（届时配额按 `enterprise_id`/`group_id` 两级）。

Kueue 是 K8s **admit-time** 配额（拿 GPU 时检查），不够。Quota Service 在 **submit-time** 做预检——拒绝"明显超额"的提交，提前给用户错误。

**四类配额**（v1）：

| 维度 | 单位 | 来源 | 检查位置 |
|---|---|---|---|
| GPU 时（30 天滚动） | GPU·hour | 训练 / SFT 提交 | `train.submit` / `sft.submit` |
| OSS 流量（每作业） | GB | 管线模板 × 输入数据集大小估算 | `pipeline.submit` |
| CPU 时（每管线） | CPU·hour | 管线模板估算 | `pipeline.submit` |
| OSS 存储字节（企业 累积） | GB | Gravitino 注册 / 模型上传时读 OSS 实际大小 | `data.register` / `model.register`；超额拒注册 |

> **OSS 流量 vs. OSS 存储** 是两个独立维度：流量是作业级吞吐（管线跑一次的临时消耗），存储字节是 企业 内 OSS 所有资产的持久占用。`laictl --admin enterprise quota update --oss-bytes` 管的是存储字节配额，不影响流量上限。

**原子预留设计**（解决并发超额放行问题）：

> ⚠️ **以下为 PG 回归后（vN+）的设计**，且依赖单体内 PG 同事务——**全拆微服务下不成立**（ADR-013）：v1 无 PG、无此服务；PG 回归后配额账本**单服务自治**，跨服务一致性走 reconcile/saga（非同事务原子预留）。下文保留作 PG 单服务内的参考。

Submit-time 配额检查必须是原子预留，而非乐观读后写入——两个大作业同时读到剩余配额充足、同时通过检查会击穿保证。**（PG 回归后）单服务内**实现：

```python
# 接口：reserve / confirm / release 三步
QuotaService.reserve(
    ctx,
    action: str,
    request_id: str,           # 幂等键，防重试双扣
    estimated_usage: dict,
) -> Reservation               # 含 reservation_id + TTL（默认 30s）

QuotaService.confirm(reservation_id: str)          # 入队成功后调用，预留转为占用
QuotaService.release(reservation_id: str, reason)  # 入队失败/取消/作业完成时调用
```

**调用顺序**（Admission Pipeline 的事务边界 = PG 本地状态 + audit + outbox；外部副作用走 outbox worker 异步执行）：

```
AuthMiddleware
  → PolicyEngine.can
  ┌─────────── PG 单事务边界（同步、毫秒级；任何一步失败整事务回滚） ───────────┐
  │ QuotaService.reserve(request_id, ...)
  │     - 桶锁 + 幂等短路（见 §3.10 表设计）
  │     - 失败返 quota_exceeded
  │ INSERT INTO workloads (workload_id, enterprise_id, action, state='pending', spec_json, ...)
  │ INSERT INTO audit_log (action, decision='allow', ...)
  │ INSERT INTO outbox_events (event_id, workload_id, kind='enqueue_kueue',
  │                            payload, status='pending', attempts=0)
  └──────────────────────────────────────────────────────────────────────────┘
  → 立即返 200 + workload_id（客户端轮询 workload 状态获知实际入队结果）

【异步】outbox worker（独立进程；按 workload_id 串行；幂等）：
  loop:
    pick event WHERE status='pending'
    case kind:
      enqueue_kueue → 调 Kueue / Volcano / Argo API（外部系统按 workload UID 幂等）
      register_gravitino → 调 Gravitino
      ... 其它外部副作用
    成功：UPDATE event SET status='done'；同时 workload 状态前进
    失败：attempts++，指数退避；超阈值挂 dead-letter + 告警
    若操作在外部已存在（按 workload UID 探测）→ 视为成功（幂等）

【异步】Kueue/Volcano/Argo informer（驱动 quota 生命周期，#4 单权威）：
  on Workload Admitted        → QuotaService.confirm(reservation_id, workload_uid)
  on Workload Finished/Failed → QuotaService.finalize(reservation_id, actual_amount, reason)
  on Workload NotFound (DELETED externally) →
                                 QuotaService.release(reservation_id, "external_deleted")

# 滚动维度（gpu_hours / cpu_hours / oss_traffic_gb）必须 finalize，不能 release——
# 否则历史用量丢失，30 天上限形同虚设；仅"并发容量"维度走 release。
```

**为什么不在同一事务里直接调外部系统**：
- Kueue/Argo/Volcano/Gravitino/OSS 是远程系统，调用耗时数百毫秒甚至秒级；放进 PG 事务会导致 audit 表上长锁、连接耗尽、admission P95 不可控。
- 外部副作用不可回滚——若 K8s 对象已创建但 PG 因 audit 写失败回滚，会产生孤儿资源。
- outbox 模式把"业务决策（PG 内）"与"外部物化（worker）"解耦，二者各自幂等。

**Outbox 表设计**（§3.11.5 / 与 audit 表同库同事务）：

```sql
CREATE TABLE outbox_events (
  event_id     TEXT PRIMARY KEY,
  workload_id  TEXT NOT NULL,         -- 业务实体 UID，外部系统去重键
  enterprise_id    TEXT NOT NULL,
  kind         TEXT NOT NULL,         -- enqueue_kueue / register_gravitino / ...
  payload      JSONB NOT NULL,
  status       TEXT NOT NULL DEFAULT 'pending',  -- pending / done / dead
  attempts     INT  NOT NULL DEFAULT 0,
  next_retry   TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_error   TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON outbox_events (status, next_retry) WHERE status='pending';
CREATE INDEX ON outbox_events (workload_id);
```

> ⚠️ 反模式：在同步 handler 内 `try: kueue.submit(); except: pg.rollback()`——Kueue 已成功创建的 Workload **不会被回滚**，下次重试会产生重复对象 / 双扣 Kueue 配额。所有外部副作用必须经 outbox。

**PG 配额表设计**：

```sql
-- 配额上限（platform-admin 设置）
CREATE TABLE quota_limits (
  enterprise_id   TEXT NOT NULL,
  dimension   TEXT NOT NULL,   -- gpu_hours / oss_traffic_gb / cpu_hours / oss_bytes
  limit_value NUMERIC NOT NULL,
  PRIMARY KEY (enterprise_id, dimension)
);

-- 预留账本（submit-time 原子写入；仅表达"当前同时占用"，不承载历史用量）
CREATE TABLE quota_reservations (
  reservation_id TEXT PRIMARY KEY,
  enterprise_id      TEXT NOT NULL,
  action         TEXT NOT NULL,                     -- "train.submit" / "sft.submit" / "pipeline.submit" / ...
  request_id     TEXT NOT NULL,                     -- 客户端幂等键（同一 request_id 重试不双扣）
  dimension      TEXT NOT NULL,
  amount         NUMERIC NOT NULL,                  -- 估算预留量
  status         TEXT NOT NULL DEFAULT 'reserved',  -- reserved / confirmed / finalized / released
  expires_at     TIMESTAMPTZ NOT NULL,              -- TTL 30s，超时自动 release
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (enterprise_id, action, request_id)            -- 幂等约束：同 request_id 重试拿回原 reservation
);
CREATE INDEX ON quota_reservations (enterprise_id, dimension, status);

-- 滚动用量账本（不可变；承载 30 天等滚动窗口的真实消耗）
CREATE TABLE quota_usage (
  usage_id       TEXT PRIMARY KEY,
  enterprise_id      TEXT NOT NULL,
  dimension      TEXT NOT NULL,
  amount         NUMERIC NOT NULL,                  -- 作业完成时的实际用量
  reservation_id TEXT,                              -- 溯源（finalize 来源）
  window_start   TIMESTAMPTZ NOT NULL,              -- 作业开始时间
  window_end     TIMESTAMPTZ NOT NULL,              -- 作业结束时间（计入滚动窗口的时间点）
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON quota_usage (enterprise_id, dimension, window_end DESC);

-- reserve 实现（单事务，必须串行化到 (enterprise_id, dimension) 桶）：
--   BEGIN;
--   -- ⓪ 幂等短路：同 (enterprise_id, action, request_id) 已存在 → 直接返回原 reservation
--   SELECT * FROM quota_reservations
--     WHERE enterprise_id=? AND action=? AND request_id=?
--     FOR UPDATE;
--   -- 找到则直接返回；否则继续 ↓
--
--   -- ① 锁住配额桶本身（行锁），保证同一 (enterprise_id, dimension) 同时只有一个事务能进
--   SELECT limit_value
--     FROM quota_limits
--    WHERE enterprise_id=? AND dimension=?
--    FOR UPDATE;
--
--   -- ② 在桶锁持有期间统计 "活跃预留 + 滚动窗口内历史用量"
--   SELECT
--     (SELECT COALESCE(SUM(amount),0)
--        FROM quota_reservations
--       WHERE enterprise_id=? AND dimension=? AND status IN ('reserved','confirmed'))
--   + (SELECT COALESCE(SUM(amount),0)
--        FROM quota_usage
--       WHERE enterprise_id=? AND dimension=?
--         AND window_end > now() - INTERVAL '30 days');   -- 滚动窗口长度按维度配置
--
--   -- ③ 合计 + 本次申请 ≤ limit → INSERT reservation（带 request_id）；
--   --    否则 RAISE quota_exceeded
--   COMMIT;
--
-- finalize 实现（confirm 后、作业真正结束时调用）：
--   BEGIN;
--   UPDATE quota_reservations
--      SET status='finalized'
--    WHERE reservation_id=? AND status IN ('confirmed','reserved');
--   INSERT INTO quota_usage(usage_id, enterprise_id, dimension, amount,
--                                  reservation_id, window_start, window_end)
--   VALUES (..., actual_amount, ..., job_start, now());
--   COMMIT;
-- finalize 也按 reservation_id 幂等：状态已是 finalized 时直接返回成功。
--
-- 备选实现：若桶不存在或不想依赖 limits 表行锁，使用
--   SELECT pg_advisory_xact_lock(hashtext(enterprise_id||':'||dimension));
-- 任选其一，关键是 reserve 全程持有 per-bucket 独占锁，禁止"先 SUM 后 INSERT"未加锁的模式。
```

> ⚠️ 反模式 1（并发）：仅对预留行 `FOR UPDATE` 不够——两个并发请求会同时看到相同的剩余量并各自 INSERT 新行（新行不在彼此的锁集合里），导致双扣。必须锁桶本身（`quota_limits` 行锁或 advisory lock）。
> ⚠️ 反模式 2（滚动绕过）：作业完成时直接 `release` 而不写 `quota_usage` 会让历史消耗从配额视图中消失——企业串行跑作业即可永远不撞 30 天上限。所有滚动维度必须走 `finalize` 路径。
> ⚠️ 反模式 3（重试双扣）：`reserve` 入参不带 `request_id`、或表上没有 `UNIQUE(enterprise_id, action, request_id)`，客户端超时重试就会两次扣额。
>
> L2 集成测试覆盖（见 §7.3）：Quota 并发、Quota 滚动累计、Quota 幂等三组用例。

**配额释放路径**（防止泄漏）：
- 入队失败：handler 捕获异常后显式调 `release`
- 作业完成/取消：Volcano webhook 或 Argo callback 调 `release`
- 超时兜底：nightly reconciler 扫 `expires_at < now() AND status='reserved'`，自动 release 并告警

**三层配额的权威分工与冲突裁决**：

| 层 | 角色 | 权威范围 | 数据源 |
|---|---|---|---|
| Quota Service（PG） | UX 预检 + 预算（滚动用量） | submit-time 拒绝明显超额 + 30 天滚动账本 | `quota_reservations` + `quota_usage` |
| Kueue（admit-time） | **GPU/CPU 并发容量的唯一运行时权威** | 决定作业是否被 admit；可抢占、重排 | `Workload.status`（ClusterQueue 实时状态） |
| Runtime 对账（nightly） | 偏差发现 + 修账，不做拒绝 | 对齐 PG ↔ Kueue ↔ 实际运行作业 | nightly job |

**核心规则**：
1. **reservation 必须绑定 Kueue `Workload UID`**：reserve 时由 outbox worker 创建 Kueue Workload 后回填到 reservation；未绑定的 reservation 超过 TTL 自动 release。
2. **confirm/finalize/release 由 informer 驱动，而不是 handler 即时调用**：
   - `Workload Admitted` → `confirm(reservation_id)`
   - `Workload Finished/Failed` → `finalize(reservation_id, actual_amount)`
   - `Workload NotFound`（被人工 `kubectl delete` 或未创建）→ `release(reservation_id, "external_deleted")`
   - callback 丢失兜底：reservation TTL（默认 30s，confirmed 后续到作业结束）+ nightly reconciler 按 Workload UID 反查。
3. **PG 与 Kueue 不一致时的裁决**（nightly job）：
   - **并发容量**（GPU/CPU 同时占用）→ **以 Kueue Workload 实际状态为准**，PG 自动修账（reservation/usage 与 Kueue 不符则按 Kueue 覆盖，并写 audit）。
   - **滚动用量**（gpu_hours/cpu_hours/oss_traffic_gb 历史累积）→ **以 PG `quota_usage` 为准**（Kueue 不保留历史）；缺失的 usage 由 nightly 从 Kueue Workload 终态补写。
4. **submit-time 行为**：PG 视图与 Kueue 不一致时，**不阻塞用户**——以 PG 视图做预检（避免依赖 Kueue 同步可用性）；真实是否能跑由 admit-time Kueue 决定。
5. **运维口径**：偏差 > 阈值告警，但**不自动阻断新提交**（防止误报雪崩）。

**运行时对账**：nightly job 对比 PG `confirmed` / `usage` 总量与 Kueue Workload 终态，按上述规则修账（O8 风险项）。

**配额账本**：超过 80% 时仪表盘黄、90% 红。

**用户故事映射**：AC-29 / 一日故事 09:30 "配额预检通过（OSS 流量 100GB / CPU 8h）"

### 3.11 Audit Layer（审计）

**v1 必做**（ADR-010 §5）。⚠️ **v1 无 PG**，故审计落 **OSS 只追加**（非 PG 同事务原子；强保证待 PG 回归）。

**模型**（OSS append-only JSON-lines，每行一条事件）：
```jsonc
// oss://lite-ai-infra/audit/{yyyy}/{mm}/{dd}/{shard}.jsonl  （只追加，不可改）
{
  "ts": "2026-06-04T...Z",
  "enterprise_id": "e-0001",
  "group_id": "g-0001",
  "actor_user": "...",        // Keycloak sub
  "actor_role": "...",        // member / group-admin / enterprise-admin / platform-admin（来自 token groups）
  "action": "job.cancel",     // "dataset.force_delete" ...
  "resource_uri": "...",
  "decision": "allow",        // allow / deny
  "override": false,          // admin override / --force 标记
  "reason": "...",            // Cerbos decision reason
  "metadata": { "ip": "...", "ua": "...", "payload_digest": "..." }
}
```

**写入路径**：
- **事后尽力写**：mutation handler 用 `@audited` 装饰器，在业务动作后**追加写 OSS**（v1 非同事务——进程崩溃可能漏记；关键路径可双写兜底）。
- **Cerbos decision log**：每次 allow/deny 由 Cerbos 自带 decision log 输出（补充覆盖）。
- **OpenSearch 索引（可选）**：Fluent Bit 读 OSS audit → `audit-{enterprise_id}-*` index，仅作 Grafana 查询视图。
- **PG 回归后**：改为 `@audited` 同事务写 PG `audit_log`（原子，真相源），OSS/OpenSearch 转为归档/视图。

**强制 audit 的动作**（v1）：
- 所有 `mutation`（POST/PUT/PATCH/DELETE）API
- 所有 `/admin/*` 路径（无论 mutation 或 read）
- 所有 `--force`（如 `data delete --force`）
- 所有 `--on-behalf` 提交
- Cerbos `deny` 决策（写 `decision=deny`，便于追"为什么拒"）

**查询接口**：
- 普通成员：无（看不到 audit）
- enterprise-admin：`GET /v1/audit?enterprise_id=<self>` 仅本企业；CLI `laictl audit list`
- platform-admin：`GET /admin/audit?enterprise_id=*` 跨企业

**v1 不做**：tamper-proof（区块链/WORM）、SIEM 集成、跨企业聚合分析视图、**同事务原子审计**（待 PG 回归）。

### 3.12 资源状态机与生命周期

> v1 引入显式状态机；决策中"看 state"的部分由 PolicyEngine 统一处理（见 §3.9 表）。

| 资源 | 状态机 | 转换触发 | mutation 约束 |
|---|---|---|---|
| 训练 Job | `pending → running → (completed \| failed \| canceled) → archived`；`archived → active`（restore）；`archived → [deleted]` | Volcano webhook | `delete` 仅 running；completed 必须 `archive`；`restore`（archived → active）仅 group-admin+；`delete(永久)`（archived → [deleted]）仅 platform-admin |
| 推理 Deployment | `deploying → healthy → (degraded \| terminated)` | readiness probe | `scale` / `tear-down` 任意状态 |
| Workspace | `creating → running → (stopped \| deleting)` | 用户 / 8h idle | `start` 仅 stopped；`enter` 仅 running，且仅 owner（group-admin v1 不可进；platform-admin 走 `/admin/*`）|
| 数据集 | `active → (deprecated \| deleting) → [deleted]` + 派生 `ref_count` | Gravitino lineage / `--force` / nightly GC | 所有 mutation 必须在 `datasets` 行锁内完成状态转换；`active→deleting` / `active→deprecated` 是同步原子操作（事务内），OSS/Gravitino 真删只在状态进入 `deleting` 之后异步执行（见下方两阶段删除）|
| 数据管线 | `pending → running → (succeeded \| failed \| canceled)` | Argo | `update params` 仅 pending 且仅 owner（group-admin 可改任意成员）；`retry` 仅 failed |
| 企业（Enterprise）| `active → (suspended \| archived)` | platform-admin | suspended 拒该企业所有用户登录；archived 仅 read-only 元数据 |

**数据集 `ref_count` 计算**（user-stories AC-23 / 表注 [1]）：
- 权威源：**Gravitino lineage 边**（dataset → run / pipeline / model）
- 写入路径：
  - 训练 / SFT 提交时，Platform API 写 `dataset → job` 边
  - 管线注册产物时，Argo callback 写 `input_dataset → output_dataset` 边
  - 模型注册时，写 `dataset → model` 边
- 查询：`GET /v1/datasets/{uri}/refs` → 聚合返回所有边及对应资源 URI + owner

**两阶段删除与 tombstone**（防止"边删边引用"竞态）：

数据集删除**禁止**单步硬删——必须先在事务内立 tombstone，再异步真删。所有"创建新引用"的路径（train.submit / sft.submit / pipeline.submit / model.register / Argo callback 写血缘）也必须在同一事务里检查状态：

```python
# 创建引用方（提交/注册类）共享的事务模板
with pg.transaction():
    ds = SELECT state FROM datasets WHERE uri=? FOR UPDATE       # 行锁
    if ds.state != 'active':
        raise dataset_not_writable(ds.state)                      # 拒 submit/register
    INSERT INTO gravitino_lineage_edges (...)                     # 同事务写血缘
    # → 事务提交后，引用才生效
```

```python
# 删除方
with pg.transaction():
    ds = SELECT state, ref_count FROM datasets WHERE uri=? FOR UPDATE
    if 普通成员 and ds.ref_count > 0:
        raise dataset_in_use(ds.ref_count)
    if --force and ds.ref_count > 0:
        UPDATE datasets SET state='deprecated' WHERE uri=?        # tombstone：拒新引用，旧引用只读
    else:
        UPDATE datasets SET state='deleting' WHERE uri=?          # tombstone：彻底拒新引用
    INSERT audit_log(...)
# 事务提交后，新 submit 立即被拒（因为状态不是 active）。
# 真正的 OSS / Gravitino 硬删由后台 deletion worker 异步执行——
# 仅当 state='deleting' 且持续 N 分钟无新引用尝试时，才真删并置为 [deleted]。
```

- **delete 决策**：
  - `ref_count == 0` + owner/group-admin：`active → deleting`（tombstone 生效，异步硬删 OSS + Gravitino）
  - `ref_count > 0` + 普通成员：拒（`dataset 被 N 个资源引用`）
  - `ref_count > 0` + `--force` + owner/group-admin：`active → deprecated`（OSS 保留；阻止新引用；现有 running job 可继续读）；audit 写入引用快照
  - `deprecated` + `ref_count == 0`：nightly GC 把 `deprecated → deleting` → 异步硬删 → `[deleted]`
  - `deprecated` + `ref_count > 0` + platform-admin gc（admin path）：`deprecated → deleting`（强制跳过 ref_count；最高破坏性；强 audit + 二次确认）

> ⚠️ 反模式：在 handler 里"先查 ref_count == 0、再调 OSS 删除"而不持有 `datasets` 行锁——并发的 submit 会在删除决策之后、OSS 真删之前写入新血缘边，导致悬空引用 / 作业运行时找不到对象。所有引用创建路径**必须**在同一事务内 `FOR UPDATE` 校验 `state='active'`，硬删**必须**滞后于 tombstone。

`laictl data delete --dry-run` 直接调 `refs` API 列出引用方，**不执行任何状态变更**（user-stories 一日故事 15:00）。

### 3.13 OSS 写权限分层（per-enterprise/group RAM + STS）

> **按最终模型（ADR-011 §5）**：OSS 是数据路径，Cerbos 决策"发不发凭据"，由阿里云 **RAM + STS 短期受限凭据**在路径级执行。下表 `{enterprise_id}` 读作两级前缀 `e-XXXX/g-YYYY`（私有）或 `e-XXXX/shared`（共享）；STS policy 限定到对应前缀。

§3.4 路径列了，但 user-stories AC-33 要求 `processed/` 区拒绝用户直写。v1 实现：**per 企业/组 两类 RAM 角色 + STS**：

| 子账号 | 名字 | 写权限路径 | 读权限路径 | 谁用 |
|---|---|---|---|---|
| user-sa | `lite-ai-{enterprise_id}-user` | `raw/{enterprise_id}/*`、`checkpoints/{enterprise_id}/*`（训练 SA）、`models/{enterprise_id}/*`（训练 SA） | `*/{enterprise_id}/*` | 用户 SDK / Workspace / 训练 Pod |
| pipeline-sa | `lite-ai-{enterprise_id}-pipe` | `processed/{enterprise_id}/*`、`embeddings/{enterprise_id}/*` | `raw/{enterprise_id}/*`、`processed/{enterprise_id}/*` | Argo Workflow ServiceAccount |

> `logs/{enterprise_id}/` 写权限给 Fluent Bit / OpenSearch 归档 job 的独立 SA（非 企业 scope）。

**资源清单（§3.2 表）相应修订**：第 11 行"OSS RAM 子账号"由 1 个改为 2 个。

### 3.14 Enterprise Provisioner（自动 provision / 状态转换）

由 §1.2 子系统 ⑬ 承担。

> ⚠️ **按最终模型（ADR-010）调整开通对象**：
> - **v1 reconcile 项**：Keycloak **Organization**（企业）+ **Group 子组骨架**（`/e-x/g-y/{admins,members}`，含角色）；OSS 前缀 + RAM/STS；Gravitino schema；MLflow experiment tag 约定；Grafana org；OpenSearch index template。
> - **v1 推迟（无 PG）**：PG `enterprise_metadata` 行、Quota 账本、Capsule/配额相关 PG 状态——预算/中央元数据回归 PG 时再纳入。
> - 身份/组织/角色的真相源是 Keycloak，Provisioner 通过 **Keycloak Admin API** 建 Organization/Group（幂等）。

**设计原则（v1 修订）**：
- **平台只维护 `Enterprise` CR + status conditions，不直接持有 10 个外部系统的命令式编排逻辑**。
- 外部资源生命周期交给 **Crossplane Compositions**（K8s 原生资源 / 云资源 / RAM）+ **ArgoCD app-of-apps**（Keycloak realm 配置 / Grafana org / OpenSearch index template / MLflow / Gravitino schema 等可声明化对象）。
- 每个外部资源都是独立 K8s 对象，**有 owner reference 指向 Enterprise CR + 独立 finalizer + 独立 condition**；不再是单进程内 10 步顺序调用。
- **v1 首发企业走人工 / IaC 创建**（terraform plan + apply），把自动 provisioner 降级为 3-4 企业落地前的 P1 能力——v1 不要求一键创建企业。

**Enterprise CR 结构**（concept）：

```yaml
apiVersion: platform.lite-ai/v1
kind: Enterprise
metadata:
  name: e-0001
spec:
  displayName: "x-user-team"
  state: active                        # active | suspended | archived
status:
  phase: Ready                         # Provisioning | Ready | Degraded | Suspended | Archived
  conditions:
    - type: KeycloakGroupReady          status: True
    - type: CapsuleTenantReady          status: True
    - type: KueueLocalQueueReady        status: True
    - type: OSSPrefixReady              status: True
    - type: RAMSubAccountsReady         status: True
    - type: GravitinoSchemaReady        status: True
    - type: MLflowExperimentReady       status: True
    - type: GrafanaOrgReady             status: True
    - type: OpenSearchTemplatesReady    status: True
    - type: AuditRecorded               status: True
```

每个 condition 由独立 controller / Crossplane composition 维护；任何一项 `False` → `phase=Degraded`，**不允许 企业 进入 Ready**。

**资源映射与责任划分**：

| 资源 | 实现方式 | finalizer 行为 |
|---|---|---|
| PG `enterprise_metadata` | Platform API 写 | 删除时校验所有 condition = False/Removed |
| Keycloak Group | ArgoCD 同步 `keycloak-config-cli` realm 文件 | suspend 时禁用登录；archive 时移除 |
| Capsule Tenant CR | Crossplane composition | 删除时阻塞，直到 ns 内无 Workload |
| Kueue LocalQueue | Crossplane composition | 删除时排空队列 |
| OSS prefix + 2 RAM 子账号 | Crossplane composition（阿里云 provider） | suspend 时**先吊销 RAM AK**，再禁 bucket 写 |
| Gravitino schema | ArgoCD job（idempotent CLI） | archive 保留只读 |
| MLflow experiment | ArgoCD job | archive 保留只读 |
| Grafana Org + Datasource | Grafana operator / Crossplane | suspend 禁登录 |
| OpenSearch index template | ArgoCD job | archive 转冷 |
| Audit `企业.create` | Platform API 同事务写 | — |

**状态机与冻结顺序**：

```
provisioning → active → (suspended | archived | failed)
suspended → active（恢复） | archived
active → archived（先经 suspended 中间态，不允许直跳）
```

**suspend 冻结顺序（必须严格按下列顺序执行，每步等待 condition 反馈再下一步，防止隔离绕过）**：

```
① 吊销 RAM 子账号 AK（OSS 写入立即失败）          ← 最早，防数据泄漏 / 写入
② Keycloak group 禁用登录（拒新会话）
③ Kueue LocalQueue 停止 admit（拒新作业）
④ Grafana Org 禁登录
⑤ OpenSearch index template 标记 readonly
⑥ 现存 K8s 运行中作业：保留（让其跑完或 owner kill）
⑦ Platform API mutation 全拒（state=suspended 时由 PolicyEngine 一票否决）
```

**archive 顺序**：先经 `suspended` ≥ 30 天 → OSS prefix 转冷归档 → K8s 资源回收 → 保留 PG / Gravitino / MLflow 只读元数据。

**Drift detection**：
- Crossplane 自带 reconcile loop（资源被人工改动 → 自动纠正或告警）
- ArgoCD 自带 OutOfSync 检测
- Platform 仅做 **cross-system invariant check**（nightly）：
  - "企业=suspended 但 Keycloak group 仍可登录" → 告警 + 拒所有 API
  - "企业=archived 但 RAM 子账号 AK 仍 active" → 告警 + 立刻吊销
  - "Capsule Tenant 存在但 Kueue LocalQueue 缺失" → 告警

**v1 不做**：
- 一键 `laictl 企业 create` 自动化（首企业人工 + IaC；3-4 企业落地前补齐）
- 跨集群 企业 拓扑
- 企业 模板 / 配额阶梯

> ⚠️ 反模式：把 10 个外部系统的 create/suspend/archive 写进一个自研单进程 reconciler 顺序调用——某一步失败 + 重试边界不明 → 半企业（可登录但无队列 / RAM 已建但 OSS prefix 未建 / suspend 撤了 Keycloak 但 OSS 仍可写）= **企业隔离绕过 + 账务漂移**。必须每个资源独立 condition + finalizer + drift detector。

### 3.16.1 共享观测面的多企业硬隔离（OpenSearch / Fluent Bit）

**问题背景**：v1 共享 OpenSearch + Fluent Bit 是平台所有企业的日志/审计查询面。单企业作业刷日志、输出高基数字段、触发 mapping 爆炸都可能压垮集群。软隔离（label + Grafana datasource filter）不足——一次 datasource 配错即跨企业漏审计。

**v1 必做（不延后到 vN+）**：

| 维度 | 措施 |
|---|---|
| **集群可用性** | StatefulSet 3 节点（master+data 合并；replica_count=1）；单节点故障不中断；本地 PV + 每日快照到 OSS |
| **企业查询隔离** | OpenSearch security plugin v1 起启用；每企业 一个 role，绑定 `logs-{enterprise_id}-*` / `audit-{enterprise_id}-*` index pattern；Grafana datasource 走 per enterprise/group role token（不再依赖 datasource filter） |
| **写入限速** | Fluent Bit per enterprise/group `mem_buf_limit` + `rate_limit`（默认 10MB/s/企业；超限 drop 并打 metric `fluentbit.drop.{enterprise_id}` 触发告警） |
| **mapping 爆炸防护** | 每个 `logs-{enterprise_id}-*` 模板设 `index.mapping.total_fields.limit=1000`；动态字段超限即 reject + 告警 |
| **索引大小防护** | ILM 策略：单 index 50GB 或 1 天 rollover；保留 14 天（hot）+ 自动转 oss://logs/{enterprise_id}/ 冷归档；per enterprise/group 总大小上限 100GB（超限 reject 并告警） |
| **PG 连接池保护** | Fluent Bit 不直接写 PG；audit 通过 Platform API 同事务写入；OpenSearch 仅从 PG CDC 复制 |

**audit 查询权威 = PG，不是 OpenSearch**：
- `GET /v1/audit?enterprise_id=...` / `GET /admin/audit?enterprise_id=*` 一律查 PG `audit_log`
- OpenSearch `audit-{enterprise_id}-*` 仅作 Grafana 可视化 / 长期检索 cache；OpenSearch 全集群挂掉**不影响**审计查询与合规导出
- 这也消除"audit 必须靠 OpenSearch 才能查"的隐式 SLA 绑定

**降级行为**：
- OpenSearch 集群 unhealthy → Fluent Bit 本地缓冲 + 排队（buffer 满即 drop 并告警）；Platform API 提交路径**不受影响**
- Grafana 日志面板 unavailable → 退化到 `kubectl logs` + PG `audit_log` 直查

### 3.16.2 Gravitino 高可用与降级（消除单点）

**问题背景**：Gravitino 同时承担"企业 schema 隔离 + 数据血缘 + 资产命名解析"，是 train.submit / sft.submit / data.register / dataset 删除两阶段决策的同步依赖。单副本 = 平台单点故障源。

**v1 必做**：

| 维度 | 措施 |
|---|---|
| **部署形态** | StatefulSet **2 副本（active-active）**；元数据全部落到共享 RDS PG（一致性由 PG 保证）；K8s Service VIP 前端做轮询；任一 pod 故障不中断 |
| **PG 后端** | 复用底座 RDS PG（已有 multi-AZ HA + 自动备份），不引入额外 DB；Gravitino schema 独占 PG database，与 MLflow / Keycloak / Platform API 资源隔离（避免连接池互相挤占） |
| **客户端缓存** | Platform API 内嵌 Gravitino client 缓存：`uri → OSS path` / `dataset → lineage` 解析结果缓存 60s（命中率 > 90% 时 Gravitino 短暂不可用不阻塞读路径）|
| **健康探测** | readinessProbe = `GET /api/metalakes/lite-ai/health`；非健康 pod 自动下线 |

**Gravitino 不可用时的平台行为（明确降级语义）**：

| 操作类型 | Gravitino 不可用时行为 | 原因 |
|---|---|---|
| `train.submit` / `sft.submit`（需解析 `gravitino://` URI） | **拒绝**，返 503 `metadata_unavailable` | 无法解析 OSS 路径，强行入队会产生找不到数据的作业 |
| `dataset.delete` / `dataset.delete --force`（需读 ref_count + 写 deprecated/deleting） | **拒绝** | 两阶段删除依赖 lineage 边查询 |
| `data.register` / `model.register`（写 schema） | **拒绝** | 资产注册必须写元数据 |
| **读路径走缓存**：`GET /v1/datasets/{uri}/refs`、SDK 解析已缓存过的 URI、Workspace 内读 dataset | **降级可用**（返缓存数据，response header 标 `X-Stale: true`） | 不阻塞用户日常工作 |
| 已 running 的训练 / SFT 作业 | **不受影响** | 启动时已解析路径，运行中不再依赖 Gravitino |
| Argo callback 写 lineage 边 | **重试 + 入 outbox**（见 §3.10）；最终一致 | 不阻塞作业完成 |

**核心原则**：
- **新提交类操作 fail-fast**（避免产生坏作业），但**读路径与运行中作业不受影响**
- audit 与 quota 真相源都在 PG，**不依赖 Gravitino**——所以"Gravitino 挂了 = 平台挂了"不成立
- Gravitino 恢复后，outbox worker 自动补回所有 pending 的 lineage 边写入

**监控**：
- Gravitino pod up count < 2 → 立刻告警（高优）
- 客户端缓存命中率 < 80% → 告警（缓存策略需调优）
- Gravitino p95 latency > 200ms → 告警

**vN+ 演进**：评估是否引入 Gravitino client-side 一致性 hash 或独立 Gravitino-PG（如果业务量证明共享 PG 是瓶颈）。

### 3.15 Keycloak 运营纪律

| 项 | 规则 |
|---|---|
| Master admin 凭证 | 锁 1Password 团队保险柜；日常**禁用**；仅救火 / IaC apply 出错时取 |
| Realm 配置 | **IaC 化**（`keycloak-config-cli` + `realm-base.yaml` 入 git）；禁止 Admin Console 直接改 |
| Apply 流程 | PR → 双签 → `apply --env=staging`（dry-run + 验证）→ `apply --env=prod`；失败回滚走 PR revert |
| 普通用户登 Admin Console | Keycloak 默认按 role 拒，无需平台额外处理（user-stories 已验收点） |
| 漂移检测 | Sprint 5 起，nightly job 跑 `keycloak-config-cli diff`，差异 > 0 告警 |

### 3.16 未登录路径白名单（Ingress）

`platform-ingress` OIDC 中间件**仅放行**以下路径不带 token：

```
GET /healthz                         # K8s readiness/liveness
GET /readyz                          # 同上
GET /realms/lite-ai/.well-known/*    # OIDC discovery
GET /                                # Portal 落地页（内部跳 Keycloak）
```

其余一律 `401`（API）/ 跳 Keycloak（Portal/Workspace/推理 endpoint）。对应 AC-18~20。

### 3.17 `laictl --admin` 子命令体系

普通业务命令走 `laictl <verb>`；admin 命令走 `laictl --admin <verb>`，CLI 客户端在请求头加 `X-Admin-Path: true`，路由进 Platform API `routers/admin/`。

| 命令 | 用途 | user-stories 来源 |
|---|---|---|
| `laictl --admin enterprise create --id <tid> --display <name>` | 创建 企业（触发 §3.14 provision） | platform-admin 一日故事 10:00 |
| `laictl --admin enterprise suspend\|archive <tid>` | 暂停 / 归档 | §角色 3 |
| `laictl --admin enterprise quota update <tid> --gpu <N> --oss-bytes <N>` | 改配额 | 一日故事 09:00 |
| `laictl --admin data list --all-enterprises --by-size` | 跨企业 容量审计（仅元数据） | 一日故事 11:00 |
| `laictl --admin data gc <uri> --reason <txt>` | 删孤儿 dataset（强 audit + 二次确认） | AC-34 / 一日故事 11:00 |
| `laictl --admin pipeline cancel <id> --reason <txt>` | 跨企业 救火 | 一日故事 13:00 |
| `laictl --admin audit list --企业 <tid>\|*` | 查 audit | group-admin / platform-admin |
| `laictl --admin workspace enter <id>` | 进任意 企业 的 Workspace（救火；强制写 audit + admin override 标记） | AC-36 / §3.8 |

普通命令侧需要新增（user-stories 已用但 §3 此前未列）：

| 命令 | 用途 |
|---|---|
| `laictl job archive <id>` | completed 作业归档 |
| `laictl job restore <id>` | archived 作业恢复为 active（group-admin+） |
| `laictl member add\|remove <user>` | group-admin 管成员 |
| `laictl train submit ... --on-behalf <user>` | group-admin 代提（owner 仍记目标用户） |
| `laictl data delete <uri> --dry-run \| --force` | dry-run 列引用方不变更状态；`--force` 跳过 owner 检查，**不跳 ref_count**：ref_count==0 时硬删，ref_count>0 时转 `deprecated`（OSS 保留）+ audit 写引用快照（仅 owner / group-admin）|
| `laictl data update <uri> --name <name> [--desc <desc>]` | 数据集元数据更新（owner 或 group-admin） |
| `laictl pipeline submit ... --large` | 提交超默认配额阈值的大管线（需 group-admin 角色；仍受 企业 总配额约束） |
| `laictl pipeline retry <id>` | failed 重跑（owner 或 group-admin；重新配额预检） |
| `laictl audit list` | group-admin 查本企业 audit |

### 3.18 调用链总览（更新版）

所有 mutation API 与 `/admin/*` 路径必须经过：

```
请求
 → Ingress OIDC（未登录跳 Keycloak；白名单见 §3.16）
 → AuthMiddleware（JWT → Context；含 user / role / enterprise_id）
 → Router 选择（routers/v1 普通 / routers/admin 特权）
 → PolicyEngine.can(ctx, action, resource)        ← §3.9
 → QuotaService.precheck(...)（仅 submit 类）       ← §3.10
 → @audited 装饰器（事务内写 audit）                ← §3.11
 → 业务 handler
 → 响应 + audit commit
```

---

## 4. 数据流详图

> 所有 mutation 流共同前置：AuthMiddleware → PolicyEngine.can → QuotaService.precheck（仅 submit）→ @audited（见 §3.18）。下文每条流不再重复，只在与默认有偏差处显式标注。

### 4.1 数据准备流（10TB 图文 → Lance）

```
laictl data prepare → Platform API (Keycloak token 校验 → 解析 enterprise_id=e-0001)
  → PolicyEngine.can(ctx, "pipeline.submit", template)         ← §3.9
  → QuotaService.precheck(ctx, "pipeline.submit",              ← §3.10
       {oss_traffic_gb: est, cpu_hours: est})
  → @audited 写 audit_log(action="pipeline.submit")            ← §3.11
  → Argo Workflow (拉 RayCluster in 企业 ns)
    step-1: ray-data-load  (从 oss://raw/e-0001/ 流式读)
    step-2: data-juicer-ops
    step-3: ray-data-write (写 oss://processed/e-0001/.lance)
    step-4: build-stats    (→ MLflow，experiment="e-0001/data-prep")
  → Gravitino schema=e_0001 注册 dataset (status=ready, schema, version)
  → tear down RayCluster
```

### 4.2 预训练流（1B 多模态 DDP）

```
platform.submit_pretrain(image, entrypoint, data_uri="gravitino://my/v1", output_model="my/multimodal-1b", gpu=4)
  → SDK：从本地 token 缓存 取 OIDC token 注入 Authorization header
  → Platform API
    → Keycloak token 校验 → 解析 enterprise_id=e-0001
    → PolicyEngine.can(ctx, "train.submit", {gpu: 4})          ← 角色门槛：>4 需 group-admin
    → QuotaService.precheck(ctx, "train.submit", {gpu_hours: est})
    → @audited(action="train.submit", on_behalf=opt)            ← --on-behalf 时 actor / owner 分离
    → "my" → "e-0001" 替换
    → Gravitino 解析 e_0001.v1 → OSS 路径 + 写 lineage edge (dataset → run)
    → MLflow 创建 run（tag enterprise_id=e-0001）
    → Kueue（LocalQueue=e-0001-g-0001）入队
    → Volcano Job in ns=e-0001-g-0001
  → 训练 Pod
    env: DATA_URI/OUTPUT_URI/MLFLOW_*/CKPT_URI/RANK/WORLD_SIZE/ENTERPRISE_ID/GROUP_ID
    Lance 流式读 → MLflow log → 30min/epoch 写 ckpt 到 oss://checkpoints/e-0001/<run_id>/
  → 完成
    artifact → oss://models/e-0001/multimodal-1b/v<N>/
    Gravitino e_0001 schema 注册 model version (lineage: dataset → model 边写入)
    Argo callback → 更新 dataset ref_count（§3.12）
```

**容错**：节点挂 → Volcano 整组重启 → 自动续训 ≤30min 前 ckpt。

### 4.3 微调流（SFT/LoRA）

```
platform.submit_sft(base_model="gravitino://my/multimodal-1b@v1", data_uri, output_model, use_lora=True)
  → 同上 token + enterprise_id 解析
  → Gravitino 解析 base_model → OSS path
  → K8s Job in ns=e-0001-g-0001（单节点 1-4 GPU）
  → 预下载 base 到 SSD → LoRA 训练 → adapter 上传 oss://models/e-0001/...
  → Gravitino 注册新版本 + lineage 边
```

### 4.4 推理部署流（vLLM）

```
platform.deploy(model="gravitino://my/multimodal-1b-sft@v1", replicas, gpu_per_replica, endpoint_name)
  → Platform API（token + enterprise_id）
    → Gravitino 解析 model → OSS artifact
    → 渲染 K8s Deployment in ns=e-0001-g-0001
        initContainer 拉 model
    → Service + Ingress（Ingress hostname 含 enterprise_id 前缀，Keycloak OIDC 保护）
  → vLLM 启动 → ready probe → OpenAI 兼容 API
  → 注册 endpoint 到 Gravitino e_0001 schema
  → Prometheus 抓 P95/QPS/GPU util（label enterprise_id=e-0001）
```

### 4.5 Embedding 批处理流

```
laictl embed batch --dataset gravitino://my/v1 --model gravitino://my/...-sft@v1 --output my/v1-embeds
  → 部署一次性 embedding 服务在 ns=e-0001-g-0001
  → Argo 拉 RayCluster
    Ray Data: lance.dataset → map_batches(call_embedding_api) → write_lance
    建索引: dataset.create_index("vector", "IVF_PQ")
  → Gravitino e_0001 schema 注册 (lineage: source dataset + model)

在线 ANN 查询（推理 Pod 内）：
  ds = lance.dataset("oss://embeddings/e-0001/v1-embeds.lance/")
  ds.to_table(nearest={"column": "vector", "q": query, "k": 10})
```

### 4.6 元数据全景（Gravitino）

```
Catalog: lite-ai-infra
└─ Schema: e_0001                     (= enterprise_id, display_name="X-user")
   ├─ datasets/   (raw-v1, v1, v1-embeds, sft-data-v1)
   ├─ models/     (multimodal-1b@v1, multimodal-1b-sft@v1)
   └─ deployments/ (chat-endpoint → multimodal-1b-sft@v1)

Lineage 边（v1 手工）：
  raw → v1 → multimodal-1b@v1
  multimodal-1b@v1 + sft-data-v1 → multimodal-1b-sft@v1
  v1 + multimodal-1b-sft@v1 → v1-embeds
```

### 4.7 跨流共用约定

| 维度 | 约定 |
|---|---|
| 用户 URI | `gravitino://my/...` 或 `gravitino://e-0001/...`；**禁止 display_name** |
| 平台内部 URI | `gravitino://e_0001.<name>@<version>` |
| OSS 路径 | 用户不直接拼，平台用 enterprise_id 解析 |
| 凭证 | K8s ServiceAccount per enterprise/group + **2 个 RAM Role**（user-sa / pipeline-sa，见 §3.13） |
| Token | 用户 → Keycloak access token → SDK 注入 → Platform API 校验 |
| 决策 | 所有 mutation 经 PolicyEngine.can（§3.9）；submit 类经 QuotaService.precheck（§3.10） |
| 审计 | mutation / `/admin/*` / `--force` / `--on-behalf` 强制 audit（§3.11） |
| Lineage | 提交训练 / 注册产物时同步写 Gravitino lineage 边（驱动 `ref_count`，§3.12） |
| 失败 | Gravitino + MLflow 同步 status=failed |
| 取消 | PolicyEngine 校验 owner / 角色 → 删 K8s 对象 + Argo + 关闭 Ray cluster |

---

## 5. 实施路径（v1–v5 递增，~25 周）

### 5.1 时间盘
- 起点：2026-06-06
- **终点（GA，v5 完成）：≈ 2026-11-28**（按合理工时顺延 v3/v4/v5 后估算，约 **25 周 / ~6 个月**）
- Sprint：S0 = 1 周；其余 2 周/sprint，共 S0–S12（13 个）
- 缓冲：最后一个 sprint（S12）不写新 feature，仅硬化/上线
- **递增交付**：每个版本完成即可独立上线（v1≈07-11 / v2≈08-22 / v3≈09-19 / v4≈10-17 / v5≈11-14）

> 上线节奏可灵活：v1/v2 完成即对客户开放（数据域 + Agent/LLM 应用），v3–v5 随后滚动发布。

### 5.2 角色简称
- **P1**：平台/K8s/训练/推理/Workspace/API Gateway/微服务脚手架
- **P2**：数据/多模态处理/元数据/向量
- **P3**：产品/SDK/CLI/**前端**/MLflow/**Keycloak·Org Service/授权(薄 can()→Cerbos)**

### 5.3 版本发布计划（总览）

> 决策（2026-06-06）：**延长时间线、不压缩深度**，v3/v4/v5 按合理工时顺延。总时长 **≈25 周（→ 2026-11-28 GA）**。基础设施贯穿；授权 v1 薄 `can()` → v2 Cerbos；身份 Keycloak 26.6.2 + Organizations（HA）；后端微服务 + API 优先；审计 OSS 追加写；**推迟（ADR-010）→ vN+**：Quota / PG 预算账本 / 同事务审计 / 中央元数据。

| 版本 | Sprint | 周 | 日期 | 交付 |
|---|---|---|---|---|
| 基础设施 | S0 | W1 | 06-06→06-13 | 地基 + Spike + Keycloak/Org + API 契约 |
| **v1 数据域** | S1–S2 | W2–5 | 06-14→07-11 | 数据管线 + 多模态处理 + 元数据 + 向量 + Dev Workspace + 数据域前端 |
| **v2 Agent + 统一 LLM** | S3–S5 | W6–11 | 07-12→08-22 | LLM Gateway（LiteLLM 选型）+ Agent 平台/对话 + 模型/管线/数据探查 agent + Cerbos |
| **v3 Agentic Search** | S6–S7 | W12–15 | 08-23→09-19 | 多源多模态统一检索 agent + 搜索前端 |
| **v4 微调** | S8–S9 | W16–19 | 09-20→10-17 | SFT/LoRA + Checkpoint/容错 + 自托管推理 + 作业/模型前端 |
| **v5 1B 预训练** | S10–S11 | W20–23 | 10-18→11-14 | 8 卡 DDP 1B baseline + 24h soak + kill drill |
| 硬化 / 上线 | S12 | W24–25 | 11-15→11-28 | 仅硬化/调优/上线（GA） |

> 下面只对**近期 S0–S2（基础设施 + v1）给出 owner 级任务表**；**v2–v5（S3–S12）给版本级 Sprint 提纲**（goal + 关键工作流 + 出口），进入各版本前再细化到 owner。

#### Sprint 0(06-06 → 06-11,✅ 已关闭):地基 + Spike + 身份骨架 + API 契约

> 关闭方式:closed with carry-over([ADR-014](../../adr/ADR-014-s0-exit1-carryover-to-s1.md));出口②③④ PASS,出口①(数据 Spike)移交 S1 门禁并已于 06-12 关闭(GO,1GB 档)。证据:`plans/2026-06-10-s0-dod-status.md`。下表为最终对账(原 3 人版任务表见 git 历史)。

| 负责 | 任务 | 状态(2026-06-12) |
|---|---|---|
| P1 | ACK 集群（GPU 节点池、网络、ACR）；Volcano + Kueue + KubeRay + Argo Helm 装 | ❌ → **S2a**(改最小云档:单 ECS+OSS) |
| P2 | **Spike 1**：Lance on OSS 读写延迟（100GB）；有 fallback 结论 | ✅ **GO,1GB 档**(内网 98–212MB/s,无需 fallback;100GB→S2a,ADR-014) |
| P2 | **Spike 2**：Data-Juicer + Ray 在 100GB **多模态图文**子集跑通；有 OOM 边界 | ✅ **GO 机制级,1GB 档**(15,138 条真图文;OOM 边界→S2a) |
| P3 | **Keycloak 26.6.2 部署**（StatefulSet + RDS PG）+ 单 realm + **Organizations** + client 初始配置（IaC 入库） | ✅(形态:ECS compose+PG 容器,符合 ADR-002 单副本;IaC=`deploy/test/`) |
| P3 | Gravitino + MLflow + 各自后端 Postgres 部署（Helm） | ❌ Gravitino → **S1 Plan 3**;MLflow → S2+ |
| P3 | **API 契约骨架（API 优先）**：`contracts/` 仓库 + OpenAPI 模板 + 代码生成流水线 + CI breaking-change 校验 | ✅ 完整(oasdiff + codegen freshness 双门禁) |
| P1/P3 | **Org Service v0 + API Gateway v0**：token 校验中间件 + 从 `groups` claim 解析 enterprise_id/group_id/role（首企业 e-0001/g-0001 兜底） | ✅ 完整+加固(JWKS 真验签/issuer 校验/seam 默认关) |

**出口(最终)**:②③④ PASS;① GO(1GB 档,100GB+ 规模验证 → S2a)。Spike A/B/C 全 PASS,结论回写 ADR-010/011;4 条 OSS 兼容性约束固化为库代码 + 回归测试。

---

#### Sprint 1(06-12 → ≈07-01,14 个工作日,🔄 进行中):数据管线 + 元数据 + 服务化

> 当前版计划真相源:[`2026-06-11-s1-data-pipeline-design.md`](2026-06-11-s1-data-pipeline-design.md)。一人 + Claude;数据规模 1GB 档(规模验证 → S2a);原 3 人版任务表见 git 历史,逐项去向见文末修订记录。

| 计划 | 内容 | 出口 | 状态(2026-06-12) |
|---|---|---|---|
| Plan 1:W1 门禁(ADR-014) | 云最小环境 + 1GB 数据集落位 + 数据 Spike 1/2 + Spike A 复验/C | 出口① 前置 | ✅ **D1 当日关闭**(早于 06-17 时限) |
| Plan 2:`pipelines/data_prep` | 一行命令:tar → DJ+Ray 清洗 → Lance on OSS 隔离路径;can()+审计入口;三层自定义开放(配方层已落地) | **①** | ✅ **已验收**(15,138 条 CC3M 真 E2E,1m43s;39 单测/3 集成) |
| Plan 3:脚手架 + identity-org-service + gateway 反代壳 | 统一 FastAPI 模板(/docs)+ `make api-docs` + 漂移守卫 CI;identity-org 迁出独立;gateway 改纯反代壳 | swagger 能力 + 服务化① | ✅ 已合并 |
| Plan 4:metadata-service | `metadata.yaml` 契约先行 + Gravitino docker 后端 + 注册/查询 + 集成 | **②** | ✅ **已合并**(层级 API/can() 过滤/fileset→Dataset;80 单元+7 集成;人工 runbook 验收)|
| Plan 5:data-pipeline-service | `data-pipeline.yaml` 契约先行 + 包 `run_prepare`(submit→job_id+查状态) | 服务化 | ✅ **已合并**(异步作业薄壳 ADR-018;JobRunner seam/单槽串行/PID 看门狗;102 单元+8 集成;独立 review;真 DJ 端到端验收)|
| Plan 6:BFF 后端 | gateway OIDC 登录/会话/登出(无状态加密 cookie,access TTL≤5min)+ CSRF + `GET /v1/data/jobs`(can()+分页);realm 加固 | **⑤**(GUI 前置) | ✅ **已合并**(全绿+一键验收 7/7+隔离评审;BFF 后端就绪,待 Plan 7 前端)|
| Plan 7:React/Vite 前端 | 数据域控制台(登录跳转 + 数据目录/数据管线/作业/我的账户),调 BFF;gateway serve `dist` | **⑤** | ⏳ |
| Plan 8:Dev Workspace | docker code-server 半天版(Pod 版 → S2) | ④(降级) | ⏳ 不阻塞 DoD |
| ~~Plan 6(原):生成式 SDK/CLI `laictl`~~ | ⏸ 推迟,**文档已删**(后续 ops/CI 工具,日后重写;commit 9a70c18 留底) | — | ADR-019 |

> **拆解原则(owner 06-13 确认)**:按服务拆 + 每服务契约优先(§3.0.1/§3.0.2);单位是服务不是技术组件。详见 S1 设计 spec §9。编号以实际计划文档为准(owner 06-14 口径 A):Plan 3=脚手架+identity-org+反代壳、Plan 4=metadata、Plan 5=data-pipeline。**出口⑤ 重定义(2026-06-18,ADR-019):CLI→真 GUI;owner 直接延长 S1(GUI 并入,工期顺延),Plan 6=BFF/7=前端/8=DevWorkspace,CLI 推迟。**

**出口(当前版)**:① 一行命令清洗→Lance ✅;② Gravitino 元数据可查 ✅(metadata-service,Plan 4 已合并);③ 薄 can() 企业隔离 ✅(S0 交付,管线已接入);服务化 ✅(metadata Plan 4 + data-pipeline Plan 5,契约先行,经 gateway can()+audit);⑤ **真 GUI 经 API 调通** ⏳(BFF Plan 6 后端 ✅ 已合并 + 前端 Plan 7 ⏳,ADR-019;原 SDK/CLI 推迟);DoD 含 code review + CI 绿 + go/no-go 签字(S1 设计 spec §7)。**S1 进度:出口①②③ + 服务化 ✅,⑤ 进展:Plan 6 BFF 后端 ✅ 已合并(全绿+一键验收 7/7+隔离评审),余 Plan 7 前端关⑤;④ Dev Workspace(Plan 8);owner 直接延长 S1。**

---

#### Sprint 2(三阶段,时间线草案见 §5.4;**S2 spec/ADR 时定稿**):**v1 交付**

> 分阶段依据:S1 设计 spec §6/§8;每阶段独立验收。下表为当前版任务分配(原 3 人单 sprint 版见 git 历史)。S2 brainstorm 开场 = 数据域前端**低保真原型**(visual companion)。

**S2a:10TB 放大 + 基础设施(≈2 周)**

| 任务 | 备注 |
|---|---|
| **Data-Juicer 跑 10TB**(关键里程碑) | 承接 ADR-014 移交:100GB+ 规模边界/真实 OOM 实测;分片 + spill 兜底(参数基线见 `spikes/datajuicer_ray/RESULTS-aliyun.md`) |
| **Lance 多写者 commit 方案** | 承接 Spike 1 约束:OSS 无条件写,fragment 并行写 + 单点 commit 模式,2–3 节点线性度实测(目标 ≥500MB/s 聚合) |
| ACK 集群 + Argo(从 S0/S1 顺延的 K8s 栈) | `runner.py` 的 `dj_fn` seam 换 Argo 提交;BYO-Step 容器 IO 契约(自定义管线层级 2) |
| Gravitino HA(2 副本 + client cache + 降级测试) | S1 Plan 3 单容器版的升级 |
| Prometheus + Grafana + DCGM 看板;P0 告警 | 含 enterprise/group label |

**S2b:向量层(≈2 周)**

| 任务 | 备注 |
|---|---|
| **Embedding 批处理**(Argo + 一次性 TEI/vLLM Pod,§3.7.1)+ **Lance ANN(IVF_PQ) 封装** | Lance 读 helper(流式 + cache)在此落地 |
| **V8 1TB 斜率测试**:端到端 embedding → Lance → ANN,外推 10TB/24h | 不达标当场决策 |
| OpenSearch + Fluent Bit 审计索引(仅观测) | 规模可按一人现实降为单节点起步 |

**S2c:产品面(≈2 周)**

| 任务 | 备注 |
|---|---|
| **前端 v1(数据域完整页面)**:数据集管理/管线提交监控/元数据浏览/实验对比 | 低保真原型已先行;OSS 静态托管 + CDN 部署;经 Gateway 走 OpenAPI 契约 |
| **Enterprise Provisioner**:`laictl --admin enterprise create` 幂等建 Org/Group/OSS 前缀/RAM-STS/Gravitino schema | 幂等跑 3 次一致 |
| **Dev Workspace 完整**(OIDC ingress + SSH + code-server 鉴权) | S1 降级版的补全 |
| URI 解析器(`gravitino://my|shared/...`)+ CLI data 命令(--dry-run/--force) | |

> **砍到 vN+(未来)**:DeepSpeed 镜像(v1 用 PyTorch DDP 已能跑 1B)。

**出口(= v1 交付)**:10TB raw → 一行命令 → Lance + Gravitino schema 可查;Embedding → ANN 可用(或 V8 决策);数据域前端完整可用;监控看板可见;`enterprise create` 幂等;Gravitino 降级可读;OSS 审计可查。

---

### v2 Agent 平台 + 统一 LLM 接入（S3–S5，W6–11，07-12 → 08-22）

> 目标：用第三方 LLM（Claude/Codex/Minimax，API key 按 token 计费）+ Agent 快速交付应用价值；授权升级到 Cerbos。详见 **ADR-012**。

**S3（W6-7）LLM Gateway + 授权升级**
- **LiteLLM 选型 spike 落定** → 部署 **LLM Gateway**（统一 chat/completion/embedding API）
- 接 **Claude / Codex / Minimax**（API key 计费）+ 模型路由 + 密钥/凭证管理 + 限流 + 按 enterprise/group 用量统计
- **Cerbos PDP 上线**，替换薄 `can()`（**AC-1~43 全过**）；LLM/数据访问按 scope 受控
- 出口：经 Gateway 用三家模型发起对话；调用按企业计量 + 授权；Cerbos 全 AC 过

**S4（W8-9）Agent 框架 + 运行时 + 统一对话**
- Agent 框架 + 运行时（规划 / 工具调用 / 多轮）；**工具走 Platform API 契约**
- **统一 chat UI**（前端）+ 会话/任务管理
- 出口：统一对话界面可用；agent 能多轮调用平台工具完成任务

**S5（W10-11）内置 agent + 前端 + 硬化**
- 内置 agent：**模型开发 / 管线开发 / 数据探查**（复用第三方模型）
- 前端 Agent/对话域完整 + LLM 用量/模型管理页；v2 预演 + 硬化
- **出口：v2 交付**——三类 agent 各完成一次真实任务；**验收 10 过**

---

### v3 Agentic Search（S6–S7，W12–15，08-23 → 09-19）

> 目标：一个 agent 对集成的多源多模态数据统一检索（**ADR-012**）。

**S6（W12-13）检索编排**
- Agentic Search 设计 spike（向量 + 全文 + 元数据融合策略）
- 检索编排：**查询规划 → 多模态检索**（Lance 向量 / Gravitino 元数据 / OSS / 全文）**→ 综合**
- 结果按 enterprise/group **scope 过滤**（数据层 + Cerbos）

**S7（W14-15）综合/引用 + 前端**
- 综合 + **带引用返回**；搜索前端（统一入口 + 多模态结果 + 引用溯源）
- v3 预演 + 硬化
- **出口：v3 交付**——自然语言查询返回带引用的跨源综合结果、scope 严格隔离；**验收 11 过**

---

### v4 微调（S8–S9，W16–19，09-20 → 10-17）

**S8（W16-17）SFT/LoRA + 容错**
- SFT 镜像 + submit_sft（LoRA / 全量；走 outbox）；training-service
- **Checkpoint 恢复完整逻辑**（SIGTERM → 保存 → 重启 → 加载，≤30min）

**S9（W18-19）推理 + 前端**
- 推理镜像 serve-vllm + inference-service（按 scope ns + Ingress；可经 LLM Gateway 统一暴露）
- 前端作业/模型页
- **出口：v4 交付**——基于现成基座 SFT/LoRA → 部署 → 推理 全链路；**验收 3/4/5 过**

---

### v5 1B 模型预训练（S10–S11，W20–23，10-18 → 11-14）

**S10（W20-21）训练跑通 + Soak**
- 训练镜像 train-pytorch-ddp + submit_pretrain（走 outbox）
- **1B 多模态 DDP 跑通**（8×A100/H800）+ Kueue **Cohort(企业)/LocalQueue(组)**
- **1B 24h soak**（GPU util / DataLoader / OSS 带宽）；RAM pipeline-sa（AC-33）

**S11（W22-23）容错 + 预演**
- **Checkpoint kill drill**（杀节点 → Volcano gang restart → 续训 ≤30min）
- 第二企业接入演练（命名审计 + suspend 顺序）；1B 全量预演 #1
- **出口：v5 交付**——1B 预训练跑通 + 24h soak GPU util ≥60% + kill drill；**验收 2 过**

---

### 硬化 / 上线（S12，W24–25，11-15 → 11-28）

| 负责 | 任务 |
|---|---|
| 全员 | 仅硬化/调优/bugfix（无新 feature）；预演 #2（全量 V1–V12 + 验收 10/11 达标） |
| P1 | 训练 GPU util 调优（≥60%×1.3）；推理 P95 + vLLM 调优 |
| P3 | **Keycloak HA 杀副本演练** + drift 检测（`keycloak-config-cli diff`）上线 |
| 全员 | 文档收口（runbook / 用户手册 / ADR）；监控告警上线；X-user 培训 |

**出口（GA ≈ 2026-11-28）**：v1–v5 全部验收达标（V1–V12 + 验收 10/11）；X-user team 独立使用全平台，团队不介入。

---

### 5.4 Hard Deadlines

> 当前版时间线(2026-06-12)。S0/S1 为事实;**S2 起为草案,S2 spec 编写时以 ADR 定稿**(宪法 §7.4);v2 及以后待 v1 交付后重排,原 5 月版日期在"原计划"列保留参照。

| 当前日期(草案) | 原计划 | Sprint | 版本里程碑 | 不达标后果 |
|---|---|---|---|---|
| ✅ 06-11 已关闭 | 06-13 | S0 | 出口②③④ PASS;出口① carry-over 并于 06-12 关闭(GO,1GB 档)——ADR-014 | (已落定) |
| **≈07-01** | 06-27 | S1 | 1GB 档数据管线(✅ 已验收)+ Gravitino 可查 + 服务化 + 契约 SDK + Dev Workspace(降级) | 砍范围 / 顺延,记录进 DoD |
| ≈07-15(草案) | — | S2a | 10TB 管线 PASS + Lance 多写者 + ACK/Argo + Gravitino HA + 监控 | 砍数据集量 |
| ≈07-29(草案) | — | S2b | Embedding/ANN + V8 1TB 斜率(不达标当场决策) | V8 砍 10% |
| **≈08-12(草案,= v1 交付)** | 07-11 | S2c | 数据域前端完整 + Provisioner 幂等 + Dev Workspace 完整 | 前端降级 |
| 待重排 | 08-22 | S3–S5 | 【v2】LLM Gateway + Agent 平台 + Cerbos 43 AC | (v1 交付后 ADR 重排) |
| 待重排 | 09-19 | S6–S7 | 【v3】Agentic Search | 同上 |
| 待重排 | 10-17 | S8–S9 | 【v4】SFT/LoRA 全链路 | 同上 |
| 待重排 | 11-14 | S10–S11 | 【v5】1B 预训练 + soak | 同上 |
| 待重排 | ≈11-28 | S12 | GA | 同上 |

### 5.5 关键路径与超载预警（按版本路线重排后）

| 风险 / 超载点 | 缓解 |
|---|---|
| **数据为早期关键路径（v1，S1–S2）**：10TB Data-Juicer 是最大里程碑 | S0 Spike 验 OOM 边界 + 分片/spill 兜底；**V8 1TB 斜率前移到 S2** 早决策（砍 10% / 推迟） |
| **v2 是最大新增工作量（Agent + LLM Gateway，S3–S5）** | **LiteLLM spike**（多 provider API key 路由 + 计量 + Python 集成）；薄 `can()`→Cerbos 用 seam 不返工；agent 工具走 Platform API 契约受治理 |
| **LLM 成本（按 token 计费）** | spike① 已结：用 **API key 按 token 计费**（非订阅，ADR-012）→ Gateway 限流 + 按 enterprise/group 计量 + 明确计费给客户/平台承担 |
| **1B 预训练（v5，S10–S11）晚发现风险** | S10 **第 1 周即 24h soak + kill drill**；用 DDP（非 DeepSpeed）降风险；S12 buffer 调优 |
| **微服务全拆 × 3 人** | **统一脚手架**（FastAPI 模板 / CI / 可观测）+ **API 契约先行**，避免每服务各搞一套 |
| **外部副作用（Kueue/Volcano/Argo/Gravitino/OSS）** | 一律走 **outbox/reconcile 幂等**，禁纳入同步链路 |
| **时间线拉长（~25 周）团队疲劳/范围漂移** | **每版本独立可上线**（递增交付，早见价值）；版本间留硬化；vN+ 严格控范围 |

### 5.6 滑窗策略

递增交付下每个版本可独立上线；范围按"不可砍 → 可降级 → 必砍"分层：

1. **不可砍（各版本核心）**：基础设施（Keycloak 26.6.2 + Org Service + **薄 can()** + **API Gateway + 契约** + OSS 审计 + 监控 + Enterprise Provisioner + OpenSearch/Gravitino HA）；**v1** 数据管线 + 多模态处理 + 元数据 + Embedding（V8 至少 10%）；**v2** LLM Gateway + Agent 平台/统一对话 + Cerbos
2. **可降级**：**v3 Agentic Search**（先单模态/单源，多源融合后补）、**v4 微调**（推理单实例 → NodePort）、**v5 1B 预训练**（soak 不达标 → 砍范围/调优）、Dev Workspace（仅 SSH）、前端（核心保住，admin 页推 vN+/CLI）、Enterprise Provisioner（全自动 → 半自动 `laictl`）
3. **已确定砍到 vN+（未来）**：DeepSpeed 镜像、CLI 高级命令、Lineage 自动化、SDK 跨语言扩展、**PG 预算/Quota Service / 同事务审计 / 中央元数据目录**（ADR-010 推迟）
4. **触发性砍项**：第二企业接入演练（若 S10 第 1 周 1B soak 失败，腾时间修训练）；LiteLLM 不达标 → 切备选 Gateway（ADR-012）

---

## 6. 风险与容错

### 6.1 P0 风险登记（必设监控/spike）

| ID | 风险 | 应对 |
|---|---|---|
| T1 | Lance + OSS 读延迟 | Sprint 0 spike；备选 JindoFS 缓存 |
| T3 | Data-Juicer 10TB OOM | Sprint 0 spike；分片 + spill；备选切批 |
| T8 | NVIDIA driver/CUDA/PyTorch 错配 | 锁基镜像；CI 兼容性测试 |
| O1 | GPU 节点不足 | Kueue 硬限；Workspace 默认 0 GPU；训练/推理节点池分离 |
| O3 | Workspace GPU 长期占用 | 8h 空闲 stop；单用户 ≤1 GPU |
| **O6** | **Keycloak 单点故障导致全平台不可用** | **HA 部署 2 副本 + RDS PG；Sprint 5 杀副本演练；Platform API 短期降级（缓存 token）** |
| S1 | X-user 模型代码延期 | 平台用公开 baseline 跑通 |
| S2 | Spike 失败 | 每 spike 有 fallback；按滑窗砍范围 |
| D1 | OSS 凭证泄漏 | ServiceAccount + RAM Role per enterprise/group；CI secret scan |
| **D5** | **资源命名混入 display_name 导致泄漏 / 难重命名** | **constitution.md 硬约束；CI 跑 grep 检查（V9 用例）；code review 强制** |
| **D6** | **PolicyEngine 漏判（handler 散落 `if enterprise_id ==`，绕过统一决策点）** | **CI grep 拦截；所有 mutation handler 单测必须 mock PolicyEngine.can 并断言被调用；43 条 AC 用例（AC-1~AC-43）全过** |
| **D7** | **Audit 写失败但业务成功（违反"audit 写失败即拒"）** | **`@audited` 装饰器内同一 PG 事务；E2E 测试故意挂 audit 表 → 期望业务回滚** |
| **D8** | **`/admin/*` 与普通路径混用导致 platform-admin 误操作跨企业** | **Router 分两个独立模块 + 各自 middleware；CI grep 禁止 admin handler 出现在 `routers/v1/`** |
| **D9** | **OSS RAM 策略错配（user-sa 误授 processed/ 写权）** | **provision 用 IaC 模板 + 单测；Sprint 2 末故意尝试 alice 写 processed/ → 期望 RAM 拒** |

### 6.2 P1 风险

| ID | 风险 | 应对 |
|---|---|---|
| T2 | Gravitino 0.6 早期版本 | 锁版本 + SDK 包裹 API |
| T4 | OSS 凭证轮转失败 | 30min 前续约 hook |
| T5 | Ckpt 写 OSS 慢 | 异步 save（local SSD → rsync OSS） |
| T6 | vLLM 多模态 1B 兼容 | Sprint 3 第一周跑通；备选 transformers |
| T9 | **Keycloak 升级 / realm 配置漂移** | **realm 配置 IaC 化（kcadm.sh 脚本入库）** |
| O2 | OSS 流量超额 | 监控 + 训练数据预下载 SSD |
| O4 | Argo/Volcano/Kueue controller 挂 | replica + PDB；runbook |
| O5 | SSO/网络隔离 | Sprint 0 提前确认 |
| O7 | **enterprise_id 与 K8s ns / OSS prefix / Gravitino schema 不一致** | **Enterprise Provisioner（§3.14）reconcile + 漂移告警；nightly 全 企业 扫一遍** |
| O8 | **Quota Service 估算偏差大（管线实际 OSS 流量 ≫ 提交时估算）** | **预检按"模板基线 × 输入数据集 size"算；运行时超 1.5x 自动告警 + admin 可强 cancel** |
| O9 | **Enterprise Provisioner reconcile 卡在某一步（如 OSS RAM 创建失败）** | **每 step 幂等 + 重试；> N 次落入 `provisioning_failed` 状态由 platform-admin 介入；不允许半新半旧** |
| S3 | 人员请假 | 知识备份 |
| S4 | 公司临时插队需求 | constitution 写明 v1 拒绝；老板背书 |
| D2 | 跨企业越权 | OSS prefix RAM 策略 + Gravitino schema RBAC |
| D3 | 数据误删 | OSS 版本管理 + 跨区复制 |
| D4 | 平台代码漏洞 | Sprint 5 安全扫描；输入校验 |

### 6.3 容错设计

#### 训练
| 故障 | 恢复机制 | 恢复时间 |
|---|---|---|
| Pod OOM | Volcano 整组重启 + 续训最新 ckpt | ≤ ckpt 间隔 |
| 节点挂 | K8s 调度 + 整组重启 | ≤ ckpt 间隔 |
| Pod evict | gracePeriod 60s + SIGTERM 保存 | 0~5 min |
| OSS 不可达 | DataLoader retry 5 次 | 0~30s |
| Ckpt 写失败 | 保留前一份 + 告警 | 续上一份 |
| **Keycloak 短暂不可用** | **Pod 已注入凭证；下次 token 刷新前不影响** | **0** |

**ckpt 间隔默认 30min，最多丢失 30min**。

#### 数据管线
| 故障 | 恢复 |
|---|---|
| Argo step 失败 | retry 3 次 |
| Ray 节点挂 | KubeRay 重建 + Ray Data 重跑分片 |
| Data-Juicer OOM | 用户重跑（产物幂等） |
| Lance 写中断 | _staging/ 原子改名 |
| Gravitino 注册失败 | dataset ready_pending + 定时 reconcile |

#### 推理
| 故障 | 恢复 |
|---|---|
| vLLM Pod 挂 | Deployment 自愈 |
| 模型加载失败 | initContainer CrashLoop + 告警 |
| 显存爆 | readiness 失败 → 摘 endpoint |
| **Keycloak 不可用** | **Ingress OIDC 缓存 token；新登录暂不可（接受短暂）** |

#### Workspace
| 故障 | 恢复 |
|---|---|
| Pod 重启 | PVC 保留代码 |
| 节点驱逐 | StatefulSet 重建 |
| 8h 空闲 | 自动 stop |

#### 身份/企业
| 故障 | 恢复 |
|---|---|
| Keycloak 主副本挂 | 第二副本接管（HA） |
| Org Service 不可达 | Platform API 缓存 enterprise_id 解析（5min TTL）|
| Realm 配置漂移 | IaC 重新 apply |

### 6.4 监控与告警

#### 关键看板
| 看板 | 指标 |
|---|---|
| 集群总览 | GPU util、节点 ready、Pending Pod、OSS 流量 |
| 训练作业 | per-run loss/throughput/GPU util/ckpt 写入（按 enterprise_id） |
| 推理服务 | P50/P95/P99/QPS/token-s/GPU mem（按 enterprise_id） |
| 数据管线 | Argo 状态、Ray 健康、清洗吞吐 |
| Workspace | 活跃数、GPU 占用、空闲分布（按 enterprise_id） |
| 平台自身 | Platform API 错误率、Gravitino/MLflow/PG/**Keycloak** 健康 |
| **企业用量** | **per enterprise/group GPU 时长、OSS 字节、作业数（v1 仅 e-0001）** |

#### P0 告警
- 训练 ckpt 30min 未写
- GPU 节点 NotReady
- Platform API 错误率 > 5%（5min）
- Gravitino / MLflow / **Keycloak** 不可用（1min）
- OSS 凭证 < 10min 未续
- Volcano / Kueue / Argo controller 挂
- **Org Service token 校验失败率 > 10%（2min）**

#### P1 告警
- 推理 P99 > baseline × 2（10min）
- Workspace 空闲 > 8h
- OSS 流量 > baseline × 3
- Kueue 队列积压（30min）

#### 日志栈（详见 ADR-005）

- **栈**：OpenSearch 2.x **StatefulSet 3 节点 cluster（replica=1）** + Fluent Bit 3.x（DaemonSet，per enterprise/group 限速）+ Grafana（OpenSearch datasource，per enterprise/group role token）
- **多企业隔离**：**OpenSearch security plugin（v1 启用）**——每企业 一个 role，绑定 `logs-{enterprise_id}-*` / `audit-{enterprise_id}-*` index pattern；Fluent Bit 按 K8s namespace metadata 注入 `enterprise_id` label；无 label 日志写入 `logs-unlabeled-*` 隔离 index；详见 §3.16.1
- **保留 + ILM**：单 index 50GB 或 1 天 rollover；保留 14 天热数据 + 自动转 `oss://logs/{enterprise_id}/{date}/` 冷归档；per enterprise/group 总大小上限 100GB（超限 reject + 告警）
- **写入限速**：Fluent Bit per enterprise/group 10MB/s（超限 drop + 告警）；`index.mapping.total_fields.limit=1000`（防 mapping 爆炸）
- **查询权限**：v1 硬隔离（security plugin role + index ACL）；**audit 权威查询走 PG，OpenSearch 仅作 Grafana 可降级视图**
- **环境差异**：dev 用 docker-compose 单容器；staging/prod 上 3 节点 StatefulSet（Sprint 1 落地）
- **故障**：3 节点任一宕机不中断；OpenSearch 全挂时 Fluent Bit 本地缓冲 + Platform API 提交路径不受影响；audit 查询降级到 PG 直查

### 6.5 故障演练

| Sprint | 演练 |
|---|---|
| 1 末 | 杀训练 Pod，验自动续训 |
| 3 末 | 杀 vLLM Pod，验自愈 |
| 4 中 | revoke OSS 凭证，验告警 |
| **5 中** | **Chaos drill：随机杀 GPU 节点 + Argo + MLflow + Keycloak 一副本** |

### 6.6 不做的容错（明确）
- ❌ 跨可用区/region 容灾
- ❌ 训练数据增量更新
- ❌ 自动降级
- ❌ 推理 A/B + 自动流量切换
- ❌ Workspace 跨节点漂移
- ❌ Keycloak 多 region

---

## 7. 验证策略

### 7.1 三层体系

| 层 | 谁 | 频率 | 形式 |
|---|---|---|---|
| L3 验收 | X-user + 平台联合 | Sprint 4/5/6 | 端到端 9 条 |
| L2 集成 | 平台团队 | sprint 末 + nightly | 子系统对接点 |
| L1 单元 | 开发者 | 每 PR | 函数/模块级 mock |

**覆盖率（写进 constitution）**：L1 ≥ 70%，L2 覆盖所有对外接口，L3 全过 = MVP 达标。

### 7.2 L3 验收用例

| ID | 用例 | 期望 |
|---|---|---|
| V1 | 数据准备闭环 | 10TB raw → Lance + Gravitino schema=e_0001 ready，48h 内 |
| V2 | 1B 多模态预训练 | 3-4 天，GPU util ≥ 60%，loss 单调降 |
| V3 | SFT/LoRA | 24h 内，adapter < 200MB，eval 优于 base |
| V4 | 推理部署 + 调用 | 5min ready，100 QPS 无 5xx，GPU mem 稳定 |
| V5 | 训练容错 | 杀 pod 5min 内恢复，丢失 ≤ 30min |
| V6 | 可观测 | 指标 ≤30s 延迟，P0 告警 5min 内推送 |
| V7 | 多企业落地 | OIDC 登录拿 token；submit 自动注入 enterprise_id；第二测试 企业 不能访问 e-0001 资源 |
| V8 | Embedding 闭环 | 10TB 24h 内，ANN ≤ 500ms |
| **V9** | **资源命名审计** | **`grep -ri "x-user" oss-paths k8s-resources gravitino-schemas mlflow-experiments` 必须为空（仅出现在 display 字段）** |
| **V10** | **PolicyEngine AC 全过** | **跑 企业-team-scenarios.md 的 43 条 AC（AC-1~AC-43，含 AC-35 pipeline 参数归属 / AC-36 Workspace 入口拒入），全 pass；Workspace enter 至少覆盖 owner / 非 owner 的 group-admin / 走 `/admin/*` 的 platform-admin 三种角色** |
| **V11** | **Audit 完整性** | **mutation / `/admin/*` / `--force` / `--on-behalf` 操作都能在 `audit_log` 查到；故意挂 audit 表 → 业务回滚** |
| **V12** | **Enterprise Provisioner 幂等** | **`企业 create e-test` 跑 3 次结果一致；中途 kill reconciler 重启能续上** |

### 7.3 L2 集成测试

| 测试集 | 内容 | 频率 |
|---|---|---|
| 训练集成 | mini DDP + enterprise_id 注入 | nightly |
| 数据管线集成 | 100MB 子集 + Gravitino schema 写 | sprint 末 |
| 推理集成 | 部署 + OIDC 调用 | nightly |
| Workspace 集成 | OIDC 登录 → 创建 → SSH → 删除 | sprint 末 |
| **多企业集成** | **创建 企业 e-test → 提作业 → 验隔离 → 删除（验 Provisioner 幂等 + V9 命名审计）** | **sprint 末** |
| **PolicyEngine AC** | **跑全部 43 条 AC 用例（AC-1~AC-43，fixture 拉两个企业 + 3 角色用户；含 AC-35 pending pipeline 参数归属 / AC-36 Workspace 入口拒入）** | **每 PR + nightly** |
| **Audit 完整性** | **mutation / admin / --force / --on-behalf 全路径 → audit_log 行匹配 + 挂表回滚** | **sprint 末** |
| **Quota 预检** | **构造超额 submit → 期望 400 + quota_exceeded reason** | **每 PR** |
| **Quota 并发** | **2 个大作业同时提交（各占配额 90%）→ 仅一个 reserve 成功，另一个返 quota_exceeded；验证无双扣** | **sprint 末** |
| **Quota 释放** | **提交成功后取消作业 → release 后再提交同量作业可通过；验证配额正确归还** | **sprint 末** |
| **Quota 滚动累计** | **串行跑 N 个小作业累计接近 30 天 GPU-hour 上限 → 第 N+1 个应被拒（quota_exceeded）；验证 finalize 写入 `quota_usage` 而非 release 丢失** | **sprint 末** |
| **Quota 幂等** | **同一 `request_id` 重复 `reserve` 两次 → 第二次返回与第一次相同的 reservation_id，配额只扣一次；UNIQUE 约束生效** | **每 PR** |
| **Dataset 删除竞态** | **并发 `dataset.delete` 与 `train.submit`（引用该数据集）→ 二者只能一个成功；submit 成功则 delete 转 deprecated，delete 成功则 submit 返 `dataset_not_writable`；事务结束后 OSS 真删才异步执行；验证不出现悬空 lineage** | **sprint 末** |
| Platform API | 全 endpoint pytest（含 token 校验失败路径） | 每 PR |

### 7.4 L1 单元测试范围

| 模块 | 重点 |
|---|---|
| URI 解析器 | gravitino:// + my/ 别名、错误格式 |
| **Org Service** | **token 解析、enterprise_id 缓存、display_name 查询** |
| **PolicyEngine** | **43 条 AC 用例（AC-1~AC-43，输入：ctx + action + resource snapshot；断言：allow/deny + reason；显式覆盖 AC-35 pipeline.update 在 pending/non-pending × owner/group-admin 矩阵，AC-36 workspace.enter 在 owner/group-admin/platform-admin 矩阵）** |
| **Quota Service** | **OSS 流量 / CPU 时 / GPU 时 预检计算；超额 / 边界 / 多维同时超 |
| **Audit 装饰器** | **正常路径写入 + 同事务回滚（mock PG 写失败）+ override / on-behalf 标记** |
| **Enterprise Provisioner** | **10 个 step 幂等 + 重启续作 + 失败状态机；mock 外部系统 |
| **Resource 状态机** | **训练/管线/Workspace/数据集/企业(Enterprise) 转换合法性表** |
| Platform API | 鉴权、配额、外部组件 mock |
| SDK | OIDC 流、token 缓存、重试 |
| Workspace Operator | 状态机、空闲检测 |
| Lance helpers | 读写、索引 |

### 7.5 性能基准

| 指标 | Sprint 4 baseline | Sprint 5 目标 | 验收 |
|---|---|---|---|
| 1B 训练 step/s | 测出 | +30% | baseline×1.3 |
| GPU util 训练 | 测出 | ≥60% | ≥60% |
| 推理 P95 | 测出 | ≤baseline | =baseline |
| 数据清洗吞吐 | 测出 | ≥100GB/h | ≥100GB/h |
| Embedding 批吞吐 | 测出 | 10TB/24h | 10TB/24h |
| **Token 校验中间件** | **测出** | **P95 ≤ 5ms** | **≤5ms** |
| **PolicyEngine 决策** | **测出** | **P95 ≤ 2ms（纯内存）** | **≤2ms** |
| **Audit 写入开销** | **测出** | **P95 ≤ 5ms（同事务）** | **≤5ms** |

### 7.6 验收判定流程

```
Sprint 6 (08-23 起)
  Day 1-2: 平台跑全部 V1-V12 自动化（含 V10 PolicyEngine 43 AC / V11 Audit / V12 Provisioner）
           + 性能基准 + Quota 并发/幂等/滚动累计 + Dataset 删除竞态测试
  Day 3:   X-user team 自跑反馈
  Day 4:   修复 + 复验（仅 bugfix；不允许新 feature）
  Day 5:   联席验收会议 → go / no-go

硬阈值（不允许 Partial 主观放行）：
  - V10 / V11 / V12 任一 fail        → 推迟 MVP
  - V2 / V5 / V8 任一性能未达标        → 推迟对应版本（V8 可走 S2 已决策的 10% 范围）
  - V1 / V3 / V4 / V6 / V7 / V9 任一 fail → 推迟对应版本
  - 全部 Pass → GA 达标（≈2026-11-28 起跑）；各版本按 §5.3 节点分别验收上线
```

### 7.7 上线后持续验证
- 每周：跑 L2 集成 + V9 命名审计
- 每月：全链路冒烟（缩量 V1-V9）
- 每季：故障演练
- 新功能：先加 L1 + L2 测试

---

## 8. 多环境策略

### 8.1 环境清单

| 环境 | 目的 | 底座 | 数据规模 | GPU | 谁用 |
|---|---|---|---|---|---|
| **dev** | 本地开发、单元 / 集成测试、改一行立即看效果 | Docker Compose（或 kind/k3d 可选） | MB 级合成数据 | CPU only（mock 训练） | 3 名平台开发者 |
| **staging** | e2e 测试、上线前演练、Chaos drill | ACK 小集群（共享） | GB 级真实数据子集 | 1-2 张 A10 | 平台团队 + X-user 联调 |
| **prod** | 实际承载训练 / 推理 / 数据 | ACK 生产集群 | TB 级真实数据 | 8 张 A100/H800 | X-user team |

**升级流向**：dev → staging → prod，配置通过 GitOps（Helm values per env）控制，**镜像不变**。

### 8.2 组件在各环境的形态

| 组件 | prod (ACK) | staging (ACK 小) | dev (Docker Compose) |
|---|---|---|---|
| **K8s** | ACK Pro | ACK Standard | docker compose（首选）/ kind（K8s 真实测试） |
| **对象存储** | 阿里云 OSS | OSS（独立 bucket） | **MinIO**（容器，S3 兼容） |
| **RDS** | 阿里云 RDS PG | RDS（小规格） | postgres 容器 |
| **Keycloak** | StatefulSet HA | StatefulSet 1 副本 | keycloak 容器 + dev realm import |
| **MLflow** | Deployment + RDS | 同 prod | mlflow 容器 + sqlite |
| **Gravitino** | StatefulSet + RDS | 同 prod | gravitino 容器 + sqlite |
| **ACR** | 阿里云 ACR | 同 prod | 本地 docker images（直接拉/构建） |
| **Volcano** | 部署 | 部署 | **不部署**（dev 跑训练用纯 Docker） |
| **Kueue** | 部署 | 部署 | **不部署** |
| **Argo Workflows** | 部署 | 部署 | **不部署**（dev 直接跑 Python 脚本替代） |
| **KubeRay / Ray** | KubeRay | KubeRay | ray 容器（单节点） |
| **vLLM/TEI** | Deployment | Deployment | 容器（CPU 模式或不跑） |
| **Workspace** | code-server K8s | code-server K8s | code-server 容器（CPU only，挂本地代码卷 + MinIO 挂载验证） |
| **Ingress** | ALB / Nginx | Nginx | docker compose port-mapping |
| **GPU** | 真实 A100/H800 | 1-2 × A10 | **mock**（训练用 1 step + tiny model） |
| **Prometheus/Grafana** | 部署 | 部署 | 容器（可选） |
| **日志栈** | OpenSearch StatefulSet + Fluent Bit DaemonSet | 同 prod（Sprint 1 上线） | docker-compose 单容器 OpenSearch + Fluent Bit；14 天保留 |
| **Platform API / SDK / CLI** | 容器化 | 容器化 | 本地 `uv run uvicorn` / `uv sync` 热重载 |

### 8.3 配置与密钥分层

```
config/
  ├─ base.yaml                 # 跨环境共享（Gravitino schema 模板、URI 协议、enterprise_id 格式）
  ├─ env/
  │   ├─ dev.yaml              # MinIO endpoint、本地 PG、Keycloak 容器地址
  │   ├─ staging.yaml          # OSS staging bucket、staging RDS、staging Keycloak
  │   └─ prod.yaml             # OSS prod bucket、prod RDS、prod Keycloak
  └─ schemas/                  # Pydantic 校验所有 env 文件结构一致

密钥：
  • dev:     .env.local（git ignore）+ docker compose secrets
  • staging: K8s Secret + ACK 凭证管理
  • prod:    K8s Secret + RAM Role（短期 STS）+ KMS 加密
```

**关键规则**：业务代码读 env vars，不读环境名。`ENV=dev|staging|prod` 仅用于 bootstrap 阶段加载哪个 yaml。

### 8.4 镜像与构建策略

```
统一构建：
  • 平台镜像（platform-api / portal / workspace-operator）一次构建，三处部署
  • 训练镜像（train-pytorch-ddp 等）prod/staging 共用；dev 可用 CPU 子镜像

dev 加速循环：
  • Platform API：本地直跑 uvicorn，连本地 docker compose 起的依赖
  • SDK/CLI：uv sync（或 uv pip install -e .），单测 + 集成测试
  • Workspace Operator：跑在 kind 上调试

构建流水线：
  • PR：构建 + 跑 L1/L2 测试（dev 环境）
  • merge to main：构建镜像 + push ACR
  • tag release：部署 staging → 跑 V1-V9 缩量 → 手动 promote prod
```

### 8.5 dev 环境的简化与权衡

**dev 默认使用 docker-compose**（不是 kind）——更轻、更快、依赖少。需要验证真 K8s 行为时切到 staging。

**dev 上的"假装"清单**（明确告诉开发者什么是不真）：

| 真实组件 | dev 替身 | 含义 / 限制 |
|---|---|---|
| Volcano gang scheduling | 直接 docker run | dev 不能验证 gang 行为 |
| Argo Workflow | Python 脚本顺序跑 step | dev 不能验证 retry/并行行为 |
| Kueue 配额 | 关闭 | dev 不能验证配额阻塞 |
| GPU 训练 | CPU + tiny model（10M 参数 + 100 步） | dev 验证代码正确性，不验性能 |
| RAM Role | MinIO root 账号（全权限） | dev 不能验证细粒度权限 |
| Keycloak 多 realm | dev realm 预导入，1 个 admin + 1 个企业 用户 | dev 简化 |
| OSS 跨区域 | 单 MinIO 实例 | dev 无 |
| K8s Ingress + DNS | localhost port-map | dev 无真实域名 |

**重要约束**：staging 必须接近 prod（K8s + OSS + 真实 GPU），用于补 dev 验证不到的能力。**dev 跑过不代表 staging 跑过；staging 跑过不代表 prod 跑过。**

### 8.6 切换环境的开发者体验

```bash
# dev：本地启动全栈
$ cd lite-ai-infra
$ make dev-up           # docker compose up -d (MinIO + PG + Keycloak + MLflow + Gravitino)
$ make dev-api          # uvicorn platform_api.main --reload
$ laictl --env=dev login
$ laictl data prepare ...   # mock 流程

# staging：跑 e2e
$ make staging-deploy   # helm upgrade -f config/env/staging.yaml
$ pytest tests/e2e --env=staging

# prod：受控发布
$ make prod-deploy TAG=v1.2.3   # 必须有 staging 通过的 commit
```

### 8.7 v1 环境策略 vs v1 不做

**v1 必做**：
- ✅ dev 环境 docker-compose 全栈（除 Volcano/Argo/Kueue/Workspace 外所有控制面组件）
- ✅ staging 环境同构 ACK 小集群（至少 1-2 GPU 节点）
- ✅ Helm chart per env values
- ✅ dev/staging/prod 镜像统一

**v1 不做**：
- ❌ 完整 GitOps（ArgoCD/Flux）——v1 用脚本 + Helm 即可
- ❌ 自动 promote（dev → staging → prod）——v1 手动 + 评审
- ❌ Preview environments per PR
- ❌ 跨环境数据迁移工具

### 8.8 Sprint 中的环境工作（增量）

> **🔄 06-12 实际口径**:S0 dev compose 只搭了 Keycloak+MinIO(够用);staging 形态改为**最小云档**(单 ECS `lite-ai-test` @ cn-hangzhou + OSS 两桶 + RAM 最小权限,IaC 在 `deploy/test/`,闲时停机);ACK/Helm 全栈推 S2a。远程执行经云助手(SSH 被本地代理掐,见 ops 备忘)。

| Sprint | 环境工作 |
|---|---|
| 0 | **dev docker-compose 全栈搭起**（MinIO + PG + Keycloak + MLflow + Gravitino + code-server workspace 容器），开发者第一天就能在本地跑 |
| 0 | staging ACK 小集群规划（节点池、network、ACR 共享） |
| 1 | platform-api / SDK 在 dev 跑通核心 endpoint（mock 训练） |
| 2 | staging 集群初始化 + 平台组件 Helm 部署到 staging |
| 3 | dev 跑通模拟训练 / SFT / 推理（CPU + tiny model）；staging 跑真实 GPU |
| 4 | prod 集群准备就绪（与 X-user 联调环境） |
| 5 | staging 跑全量预演 #2（性能验证）；prod 仅承接最后联调 |
| 6 | prod 上线（X-user 起跑） |

**预算影响**：staging 集群常开，按 1-2 张 A10 × 24h 估算成本（约整个项目预算的 5%），值得。

### 8.9 环境相关风险（补 §6）

| ID | 风险 | 应对 |
|---|---|---|
| **E1** | dev 与 prod 行为漂移（"我本地能跑"） | 关键路径必须经过 staging 验证；CI 跑 staging smoke |
| **E2** | dev MinIO 与 OSS 协议差异 | 选用 boto3 + S3 兼容接口，**不用 OSS 专属 SDK**；不可避免则在抽象层封装 |
| **E3** | dev Keycloak realm 配置漂移 | realm 配置 IaC 化（kcadm.sh）；prod/staging/dev 同源生成 |
| **E4** | staging 资源不足导致测试卡 | staging 仅短期占用 GPU；预算独立 |
| **E5** | 跨环境配置变量遗漏（如 dev.yaml 加了 key 但 prod.yaml 漏掉） | Pydantic schema 强制校验；CI 跑 config diff |

---

## 附录 A：术语表

| 术语 | 含义 |
|---|---|
| Enterprise（企业）| 对外客户；**计费/合规/隔离的硬边界**（`enterprise_id`，如 `e-0001`）= Keycloak Organization |
| Group（用户组）| 企业内的团队/组；**私有资源归属单元**（`group_id`，如 `g-0001`，企业内唯一）= Keycloak Group 子组 |
| enterprise_id / group_id | 不透明标识，用于所有资源命名（私有资源两级：`e-xxxx`+`g-yyyy`；共享：`e-xxxx`+`shared`）|
| display_name | 企业/组的人类可读名（如 "X-user"），仅用于 UI/日志，**严禁进资源名** |
| X-user team | v1 首个客户：企业 `e-0001` 下的用户组 `g-0001`（display_name=X-user）|
| Lance | 列存数据格式，原生支持向量列 + ANN（开源） |
| Gravitino | Apache 开源元数据 catalog（schema = enterprise_id） |
| MLflow | 实验跟踪服务（experiment 按 enterprise_id tag） |
| Keycloak | 开源 OIDC IdP，承担身份认证 + 企业/用户/角色管理 |
| Org Service | Platform API 内置模块：token 校验、enterprise_id 解析、企业元数据 |
| Data-Juicer | 阿里多模态数据清洗工具，跑在 Ray |
| Volcano | K8s 批处理调度器（gang scheduling） |
| Kueue | K8s 队列 + 配额引擎 |
| KubeRay | Ray on K8s operator |
| code-server | 浏览器版 VSCode（开源） |
| Workspace | 用户开发环境 Pod（code-server + sshd + enterprise_id 隔离） |

## 附录 B：相关链接

- Lance: https://github.com/lancedb/lance
- Apache Gravitino: https://gravitino.apache.org
- Data-Juicer: https://github.com/modelscope/data-juicer
- Volcano: https://volcano.sh
- Kueue: https://kueue.sigs.k8s.io
- KubeRay: https://github.com/ray-project/kuberay
- vLLM: https://docs.vllm.ai
- TEI: https://github.com/huggingface/text-embeddings-inference
- code-server: https://github.com/coder/code-server
- Keycloak: https://www.keycloak.org

## 变更记录(Change Log)

正文始终为**最新版**;历史版本看 git;路线级变更按宪法 §7.4 走 ADR。本表为变更索引(新变更追加在表尾)。

| 变更 | 出处 | 状态 |
|---|---|---|
| 团队 3 人 → 一人 + Claude;各 sprint 单线程重排 | S1 设计 spec §0 | 生效 |
| S0 关闭(出口②③④ PASS;出口① carry-over → S1 门禁) | **ADR-014**(Accepted 06-11)+ `plans/2026-06-10-s0-dod-status.md` | 已关闭 |
| S0 出口① 门禁关闭:数据 Spike 1/2 **GO(1GB 档)**;100GB+ 规模验证移 S2a | ADR-014 门禁关闭记录(06-12) | 已关闭 |
| S1 重排:14 工作日(06-12→≈07-01)、1GB 档、服务化纳入、Dev Workspace 降级 | `specs/2026-06-11-s1-data-pipeline-design.md` | 出口①②③⑤ 已验收/关闭(2026-06-24);Plan 9 Dev Workspace 降级待做 |
| 数据 Spike 工程结论:OSS 拒 path-style / boto3≥1.36 checksum / Lance 需 commit_lock+bucket-in-endpoint / 内网 endpoint 必须 | `spikes/*/RESULTS-aliyun.md`(已固化为库代码+回归测试) | 生效 |
| Keycloak claims:多组全路径 ✓、变更对新 token ~100ms、stale 窗口=accessTokenLifespan(300s) | ADR-010 附录 C(本地+阿里云双验) | 生效 |
| Cerbos seam:同 can() 签名零改 handler,v2 切换无架构风险 | ADR-011 附录 | 生效 |
| S2 分三阶段(a:10TB+HA / b:Embedding+V8 / c:前端+Provisioner);v1 交付日后移 | S1 设计 spec §6;**S2 计划时走 ADR 定稿** | 待 S2 ADR |
| 前端:低保真原型先行于 S2 spec;部署=OSS 静态托管+CDN | S1 设计 spec §6 | 待 S2 |
| 用户自定义管线三层开放(配方/BYO-Step 容器/自定义算子) | S1 设计 spec §8 | 层级 1 已落地 |
| 测试环境形态:最小云档(单 ECS+OSS),ACK 推 S2a | `deploy/test/` + `docs/ops/2026-06-09-…md` | 生效 |

| §5.3/§5.4 正文重写为当前版(S0 关闭摘要 / S1 五计划表 / S2 三阶段表 / 时间线草案列) | 本次提交(06-12);原 3 人版见 git 历史 | 生效 |
| v1 交付日草案 ≈08-12(S2a/b/c 各约 2 周) | §5.4 草案列;**S2 ADR 定稿** | 草案 |
| API 优先纠偏:S1 剩余按「服务 + 契约优先」重拆为 Plan 3–7(脚手架 / identity-org / metadata / data-pipeline / SDK);Plan 2 库+CLI 先行序为偏差,代码作服务内部实现复用(非返工) | S1 设计 spec §9(owner 06-13) | 生效 |
| identity-org-service 严格独立拆分(不折叠 gateway);手写 CLI 降级 ops 后门,产品 CLI 契约生成 | S1 设计 spec §9.1 | 生效 |
| 计划编号统一口径 A:以实际计划文档为准(Plan 3=脚手架+identity-org+反代壳、4=metadata、5=data-pipeline、6=SDK);早先草拟的 5 计划序中 Plan 3+4 被实际 Plan 3 文档合并交付,整体回退一位 | S1 设计 spec §9.3(owner 06-14) | 生效 |
| §3.0.4 目录树补全:加 `libs/`/`pipelines/` 实现层 + `spikes/`;服务目录命名改下划线 `_service`(Python 包约束);各目录标 ✅/⏳ 与建于哪个 Plan | §3.0.4(06-13) | 生效 |
