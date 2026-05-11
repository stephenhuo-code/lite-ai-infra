# Lite AI Infra Platform 设计文档

> **状态**：Draft v2（v1 起即多租户架构）
> **作者**：平台团队（3 人）
> **日期**：2026-05-08
> **目标上线**：2026-08-01（X-user team 起跑 1B 多模态预训练）

---

## 0. Executive Summary

### 项目定位
公司级共享 LLM/多模态训练 + 微调 + 推理平台。**v1 仅服务 X-user team（1B 多模态全链路）**，但**架构从第一天起就是多租户的**——通过 Keycloak 做身份/租户管理，所有资源标识与租户名解耦，未来扩展到 5+ 团队**不需要重命名任何资源**。

### 核心架构原则（写进 constitution）

> **资源标识用不透明的 `tenant_id`，团队名只是 Keycloak 里的 `display_name`。**
> 所有 OSS 路径、K8s namespace、Gravitino schema、模型 URI 一律使用 `tenant_id`；`display_name` 仅出现在 UI、日志、文档中。

### 核心约束
- **3 人** × **12 周**（2026-05-08 → 2026-08-01）
- **环境拓扑**：
  - **prod**：阿里云 ACK + OSS（不使用 PAI / PAI-DLC）
  - **dev**：本地 Docker Compose（MinIO 替 OSS、kind/k3d 可选替 K8s、CPU 替 GPU、mock 跳过 Volcano/Argo）
  - **staging**：ACK 小集群（与 prod 同构，e2e 测试用）
- **身份**：Keycloak（v1 部署，单 realm + 多 client/group）
- **数据栈**：Ray Data + Data-Juicer + Lance（开源）
- **训练栈**：PyTorch DDP / DeepSpeed（v1）；Megatron 通过镜像契约 v2 接入
- **元数据**：Apache Gravitino（资产 catalog）+ MLflow（实验跟踪）
- **首个租户任务**：10TB 图文，1B 多模态，单节点 8 GPU，3-4 天训练

### 战略路线
**路线 1（垂直优先）+ 路线 2（最大化用 OSS）+ 多租户架构从 v1 起**：
- 范围：v1 实际只服务 X-user team（一个租户落地）
- 实现：所有可用 OSS 都用，3 人聚焦"粘合 + 租户/身份层 + SDK + 内部门户"
- 多租户：v1 单租户落地但架构完整；v2 仅扩展租户数量、不动资源命名

### v1 范围（一句话）
**X-user team（首个租户）在 2026-08-01 能在平台上完成"10TB 数据准备 → 1B 预训练 → SFT → 推理部署 → Embedding 检索"全链路；3-4 天内完成预训练；节点故障 1h 内自动恢复；任意资源标识不含团队名。**

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
│ 身份 / 租户层（v1 必做）                                     │
│   ⑩ Keycloak（OIDC IdP + tenant 注册中心）                  │
│   ⑪ Tenant Service（Platform API 内：tenant_id 解析、       │
│      成员管理、display_name ↔ tenant_id 映射）              │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 控制平面（自研薄层）                                        │
│   ② 配额（Kueue ClusterQueue/LocalQueue per tenant）        │
│   ③ 实验元数据（MLflow 集成）                                │
│   Platform API（FastAPI）                                   │
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
│   (按 tenant_id) │                  │                      │
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
| ① | Portal + SDK + CLI | 提交作业、查询、列表；自动注入 tenant_id | 自研，Portal 只读为主 |
| ② | 配额 | 按 tenant_id 隔离 Kueue 配额 | LocalQueue per tenant |
| ③ | 实验元数据 | 训练参数/指标/artifact tracking | MLflow 单实例（experiments 按 tenant_id 分组） |
| ④ | 数据管线 | 10TB 图文清洗 → Lance | Ray Data + Data-Juicer + Argo |
| ⑤ | 数据存储 + 目录 | 数据/模型资产管理（按 tenant_id 分区） | OSS + Lance + Gravitino |
| ⑥ | 训练运行时 | 1B 预训练 + SFT | K8s Job + Volcano + torchrun + DDP/DeepSpeed |
| ⑦ | Checkpoint + 容错 | 训练故障恢复 | OSS ckpt + Volcano gang restart |
| ⑧ | 推理服务 | HTTP API 推理 + embedding | vLLM + TEI |
| ⑨ | Dev Workspace | 浏览器 VSCode + Remote-SSH | code-server + sshd Pod |
| **⑩** | **Keycloak** | **OIDC IdP + 租户/用户/角色注册中心** | **StatefulSet + RDS PG** |
| **⑪** | **Tenant Service** | **租户 CRUD、tenant_id ↔ display_name 解析、token 校验中间件** | **Platform API 内置模块** |
| Ⓐ | 监控 | GPU/作业/IO/平台健康 | Prometheus + Grafana + DCGM |
| Ⓑ | CI | 平台代码 + 镜像构建 | GitHub Actions + ACR |
| Ⓒ | 日志 | 集中日志查询 | OpenSearch（v1 单副本）+ Fluent Bit 采集 + Grafana 可视化（详见 ADR-005） |

### 1.3 三人分工

| 角色 | 负责子系统 |
|---|---|
| **P1**（平台/K8s/训练/推理重） | ⑥ ⑦ ⑧ ⑨ ② Ⓐ Ⓑ |
| **P2**（数据重） | ④ ⑤ + Lance VectorTable 抽象 |
| **P3**（产品/集成重） | ① ③ ⑩ ⑪ + Anchor team 接口人 |

---

## 2. MVP 范围切片

### 2.1 v1 验收标准（8 条 + 1 条架构标准）

1. **数据**：10TB 原始图文 → Data-Juicer 清洗 → Lance 数据集 → Gravitino 注册（按 tenant_id schema）
2. **预训练**：SDK 提交 1B 多模态预训练，单节点 8 GPU DDP，3-4 天完成
3. **微调**：基于 pretrain artifact 提交 SFT/LoRA，新模型版本登记
4. **推理**：微调模型部署成 HTTP 服务（vLLM），有 P95 延迟基准
5. **容错**：训练中断能从 ckpt 自动恢复，丢失进度 ≤ 1 小时
6. **可观测**：训练 + 推理指标实时可看（MLflow + Grafana）
7. **多租户落地**：X-user team 注册到 Keycloak 成为首个 tenant；所有资源（OSS 路径 / K8s ns / Gravitino schema / MLflow experiment）通过 tenant_id 引用；用户 SDK 调用时由 Tenant Service 自动从 token 解析 tenant_id
8. **Embedding 闭环**：批量生成向量 → Lance + IVF_PQ 索引 → ANN 查询可用
9. **架构标准（新增）**：grep 全部资源命名（OSS bucket prefix / K8s 资源 / Gravitino / MLflow），**任意 display_name（如 "x-user"）不得出现在资源标识中**

### 2.2 v1 必做（按交付优先级）

| 优先级 | 子系统 | 验收点 |
|---|---|---|
| **P0** | 训练运行时 | 8 卡 DDP 跑通 1B baseline |
| **P0** | Checkpoint + 容错 | 杀 pod 自动恢复 |
| **P0** | 数据管线 | 10TB 跑通 Lance |
| **P0** | 监控 | GPU/作业/IO 看板 |
| **P0** | 推理服务 | HTTP API 可调，有 P95 延迟数据 |
| **P0** | **Keycloak + Tenant Service** | **OIDC token 校验中间件 + tenant_id 解析** |
| **P1** | 微调工作流 | LoRA / SFT 跑通 |
| **P1** | 元数据 catalog | Gravitino 按 tenant_id schema 注册 |
| **P1** | 实验追踪 | MLflow experiment 按 tenant_id 分组 |
| **P1** | SDK + CLI | submit_pretrain/sft/deploy/workspace（自动 tenant_id 注入） |
| **P1** | Embedding 服务 + 向量 | TEI/vLLM + Lance + IVF_PQ |
| **P1** | Dev Workspace | code-server + Remote-SSH（按 tenant 分配） |
| **P2** | Kueue 配额 | LocalQueue per tenant，硬限 |
| **P2** | Portal | 只读列表 + 跳转 |
| **P2** | CI | 平台代码 + 镜像 |

### 2.3 v1 明确不做

- ❌ 多机分布式预训练（架构留口子）
- ❌ 推理 HPA / 灰度 / A/B / 多模型路由网关
- ❌ 自动 lineage 追踪（手工 Gravitino tag）
- ❌ 跨租户审计 / 操作日志归档
- ❌ 数据脱敏 / 隐私合规
- ❌ Web UI 提交作业（CLI/SDK 即可）
- ❌ Megatron / NeMo（v1 用 DDP/DeepSpeed）
- ❌ Ray Train（v1 训练不用 Ray，仅数据管线用 Ray Data）
- ❌ LanceDB（用开源 Lance + 自封装 VectorTable）
- ❌ 跨可用区/region 容灾
- ❌ Keycloak 高级特性：SAML、social login、自助注册、密码策略复杂规则（v1 单 realm + 公司 LDAP/AD 联邦或本地用户即可）
- ❌ 多 tenant 跨域共享数据（v1 严格隔离）

### 2.4 v1 → v2 演进点

| 现在留口子 | v2 补全 |
|---|---|
| Keycloak 单 realm + 一个 tenant | 多 tenant 上线（仅在 Keycloak 加 group/role + Tenant Service 注册新 tenant_id；**资源命名零改动**） |
| LocalQueue per tenant 简单配额 | 真正的 quota engine（多维：GPU/CPU/storage/cost）+ 审计 |
| 单节点训练 | 多节点 FSDP/Megatron + Volcano gang + eRDMA |
| 单实例 vLLM | 多模型推理网关 + HPA + 金丝雀 |
| 手工 Gravitino tag | OpenLineage 自动血缘 |
| 训练镜像契约 | 加 train-megatron / train-ray 镜像 |

### 2.5 X-user Team（首个租户）配合契约

- 提供 1B baseline 模型代码 + tokenizer
- 提供 SFT 数据样本（小集合先跑通，再上量）
- 数据上传到约定 OSS 路径（路径由平台分配的 `tenant_id` 决定）+ 提供 schema
- 推理接口的 I/O 契约
- 注册成员到 Keycloak（首批 N 人）

---

## 3. 技术架构与选型

### 3.1 完整组件清单

| 类别 | 组件 | 版本 | 部署形态 |
|---|---|---|---|
| **底座** | 阿里云 ACK | Pro 1.30+ | 托管 K8s |
| | 阿里云 OSS | — | 标准存储 + 归档 |
| | ACR | — | 镜像仓库 |
| | RDS PostgreSQL | 16 | 托管，给 MLflow + Gravitino + Keycloak + Platform API |
| **身份/租户** | **Keycloak** | **24+** | **StatefulSet（HA 2 副本）** |
| | **Tenant Service** | **自研** | **Platform API 内置模块** |
| **调度** | Volcano | v1.9+ | gang scheduling |
| | Kueue | v0.7+ | 队列 + 配额（按 tenant） |
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
| **元数据** | Apache Gravitino | 0.6+ | StatefulSet（catalog 按 tenant_id schema） |
| | MLflow | 2.16+ | Deployment（experiment 按 tenant_id tag） |
| **观测** | Prometheus | 2.54+ | kube-prometheus-stack |
| | Grafana | 11+ | 同上（OIDC 接 Keycloak） |
| | DCGM Exporter | 3.3+ | DaemonSet |
| | OpenSearch | 2.x | StatefulSet 单副本（v1）+ 本地 PV，14 天保留；冷归档 oss://logs/{tenant_id}/；v2 上 HA + ILM |
| | Fluent Bit | 3.x | DaemonSet，按 K8s namespace 注入 `tenant_id` label |
| **平台自身** | Platform API | 自研 | FastAPI（Python 3.11，Keycloak token 校验中间件） |
| | SDK | 自研 | Python pkg（自动注入 token + tenant_id 解析） |
| | CLI（laictl） | 自研 | Python click（首次用 `laictl login` 走 OIDC device flow） |
| | Portal | 自研 | Next.js（OIDC 接 Keycloak） |
| | Workspace Operator | 自研 | controller-runtime |
| **Workspace** | code-server | 4.92+ | dev 镜像内 |
| | OpenSSH | — | dev 镜像内 |

### 3.2 租户模型（核心）

#### 标识符规范

```
tenant_id 格式：
  • OSS / K8s / 大多数路径：t-XXXX           (如 t-0001)
  • Gravitino schema：     t_XXXX           (下划线，SQL 兼容)
  • MLflow tag：           tenant_id=t-0001
  • Keycloak group：       /tenants/t-0001
  • display_name：         "X-user"          (Keycloak attribute)

X-user team 在 v1 = tenant_id "t-0001"，display_name "X-user"
```

#### Tenant Service 核心 API

```python
# Platform API 内部
GET  /tenants/me               # 从 token 解析当前用户的 tenant_id 列表（一般 1 个）
GET  /tenants/{tenant_id}      # 查 tenant 信息（display_name、配额、成员数）
POST /admin/tenants            # 创建 tenant（管理员）
POST /admin/tenants/{id}/members  # 加成员

# 用户调用 SDK 时不传 tenant_id；SDK 从 OIDC token 拿
```

#### Keycloak Realm 设计（v1）

```
Realm: lite-ai-infra
  Clients:
    • platform-api      (confidential, server-side token validation)
    • cli               (public, device-code flow)
    • portal            (public, authorization code + PKCE)
    • workspace-ingress (confidential, OIDC proxy)
    • grafana / mlflow  (confidential, OIDC integration)
  Groups:
    • /platform-admins  (跨 tenant 管理员)
    • /tenants/t-0001/  (X-user team)
        ├─ members
        └─ admins
  User Federation: 公司 LDAP/AD（如有）；否则本地用户
```

#### 多租户资源全景图

```
                  ┌─────────────── Tenant (t-0001) ───────────────┐
                  │                                               │
 身份层           │  Keycloak Group: /tenants/t-0001              │
 (Identity)       │   ├─ Members: User[]                          │
                  │   └─ Roles:   tenant-admin / tenant-member    │
                  │                                               │
 配额层           │  Capsule Tenant CR: t-0001                    │
 (Quota)          │   ├─ Namespace 列表: tenant-t-0001-{用途}     │
                  │   ├─ ResourceQuota: GPU / CPU / Mem           │
                  │   ├─ NetworkPolicy                            │
                  │   └─ RBAC RoleBinding                         │
                  │                                               │
 存储层           │  OSS Prefix: oss://lite-ai-infra/.../t-0001/  │
 (Storage)        │   ├─ raw / processed / embeddings             │
                  │   ├─ checkpoints / models                     │
                  │   └─ logs (冷归档自 OpenSearch)               │
                  │                                               │
 元数据层         │  Gravitino Schema: t_0001                     │
 (Metadata)       │   ├─ Catalog 资产注册                         │
                  │  MLflow Experiments (tag: tenant_id=t-0001)   │
                  │  PG: tenant_metadata 行级隔离                 │
                  │                                               │
 工作负载层       │  K8s Workloads（装在 tenant ns 里）           │
 (Workload)       │   ├─ Volcano Job (训练)                       │
                  │   ├─ Deployment (vLLM / TEI 推理)             │
                  │   ├─ Workspace Pod (code-server)              │
                  │   ├─ Argo Workflow / Ray Cluster              │
                  │                                               │
 调度层           │  Kueue LocalQueue: tenant-t-0001-queue        │
 (Scheduling)     │                                               │
 网关层           │  Ingress Hosts: *.t-0001.lite-ai.local        │
 (Networking)     │                                               │
 观测层           │  OpenSearch Index: logs-t-0001-*              │
 (Observability)  │  Grafana Org / Datasource: t-0001             │
                  │  Prometheus labels: tenant_id=t-0001          │
                  │                                               │
 凭证层           │  Vault / KMS: secret/tenants/t-0001/  (v2)    │
 (Secrets)        │  v1 走 OSS RAM 子账号 + env var               │
                  │                                               │
 审计层           │  Audit Log: tenant_audit_log（按 tenant_id）  │
 (Audit)          │                                               │
                  └───────────────────────────────────────────────┘
```

#### 完整资源清单（v1 必管 + v2 演进）

| # | 资源类型 | 系统 | 命名规则 | 创建时机 | v1 / v2 |
|---|---|---|---|---|---|
| 1 | Tenant 元数据记录 | PG | `tenant_metadata` 表，pk = `tenant_id` | 租户创建 | v1 |
| 2 | Group | Keycloak | `/tenants/{tenant_id}` | 租户创建 | v1 |
| 3 | Role | Keycloak | `tenant-admin` / `tenant-member`（realm 级） | 一次性 | v1 |
| 4 | Capsule Tenant CR | K8s | name = `tenant_id` | 租户创建 | v1 |
| 5 | Namespace | K8s | `tenant-{tenant_id}` 或 `tenant-{tenant_id}-{用途}` | 按需，Capsule 托管 | v1 |
| 6 | ResourceQuota | K8s | Capsule 自动下发 | 跟随 Tenant CR | v1 |
| 7 | NetworkPolicy | K8s | Capsule 自动下发 | 跟随 Tenant CR | v1 |
| 8 | RBAC RoleBinding | K8s | Capsule 自动下发 | 跟随 Tenant CR | v1 |
| 9 | Kueue LocalQueue | K8s | `tenant-{tenant_id}-queue` | 租户创建 | v1 |
| 10 | OSS Prefix | OSS | `oss://lite-ai-infra/.../{tenant_id}/` | 租户创建 | v1 |
| 11 | OSS RAM 子账号 / STS Role | RAM | `lite-ai-{tenant_id}` | 租户创建 | v1 |
| 12 | Gravitino Schema | Gravitino | `t_{tenant_id_underscored}`（如 `t_0001`） | 租户创建 | v1 |
| 13 | MLflow Experiment | MLflow | tag `tenant_id={tenant_id}` | 用户首次创建 run 时 | v1 |
| 14 | OpenSearch Index Pattern | OpenSearch | `logs-{tenant_id}-*` | Fluent Bit 自动 | v1 |
| 15 | Grafana Datasource / Org | Grafana | per-tenant datasource | 租户创建 | v1 |
| 16 | Ingress Host | K8s Ingress | `*.{tenant_id}.lite-ai.local` | 部署推理 / Workspace 时 | v1 |
| 17 | TLS Cert（per-tenant 子域） | cert-manager | wildcard 或 per-host 自动签发 | 跟随 Ingress | v1 |
| 18 | 训练 Job | Volcano | `train-{tenant_id}-{run_id}` | 用户提交 | v1 |
| 19 | 推理 Deployment | K8s | `inf-{tenant_id}-{model}-{ver}` | 用户部署 | v1 |
| 20 | Workspace Pod | K8s | `ws-{tenant_id}-{user}` | 用户起 | v1 |
| 21 | Argo Workflow | K8s | `flow-{tenant_id}-{job}` | 数据管线触发 | v1 |
| 22 | Audit Log 记录 | PG / OpenSearch | per-tenant table 或 index，含 `tenant_id` 列 | 每次操作 | v1（业务侧自记录）/ v2 强化 |
| 23 | Vault / KMS Secret Path | Vault | `secret/tenants/{tenant_id}/*` | 租户创建 | v2 |
| 24 | Cost Center / Billing | 自研 | per-tenant cost ledger | — | v2 |

> 标识符规则统一遵循上文"标识符规范"小节；`display_name` 严禁出现在任何资源名 / 路径 / schema / index 中（v1 验收硬约束第 9 条）。

#### 隔离强度矩阵

| 隔离维度 | v1 强度 | 实现机制 | v2 加强 |
|---|---|---|---|
| 计算（K8s） | **强** | namespace + Capsule 强制 NetworkPolicy + ResourceQuota + RBAC | — |
| 存储（OSS） | **中-强** | RAM 子账号 + 路径 prefix + bucket policy（每 tenant 一个 RAM 子账号） | — |
| 元数据（Gravitino） | **中** | per-tenant schema + schema 级 ACL | RBAC 加强 |
| 实验（MLflow） | **弱** | tag 软隔离 + Tenant Service 中间件硬过滤 | 接 OSS 版 RBAC 或迁 commercial |
| 日志（OpenSearch） | **弱** | label + Grafana datasource filter | OpenSearch RBAC plugin（详见 ADR-005） |
| 网络（Ingress） | **强** | per-tenant 子域 + OIDC 鉴权 | — |
| 凭证 | **弱** | env var + OSS RAM 子账号（共享存储位置） | Vault per-tenant path（v2 落地） |
| 监控指标 | **中** | Prometheus label `tenant_id` + Grafana org | — |
| 审计日志 | **弱** | 业务侧自记录到 PG / OpenSearch | tamper-proof + 跨系统统一审计 |
| 调度（Kueue） | **强** | per-tenant LocalQueue + ClusterQueue 配额借用规则 | — |

#### 多租户机制硬纪律（写进 constitution）

1. **`TenantId` 是独立类型**（Types 层），不与 string 互转；构造任何资源标识符的函数签名只接收 `TenantId`
2. **资源命名必须含 `tenant_id`**；`display_name` 严禁出现在资源名 / 路径 / schema / index / label
3. **JWT claim → `TenantContext` → 注入下游** 是唯一的 tenant 来源；handler 不允许从 query/body 直接读 `tenant_id`
4. **每次访问决策必须经过 PolicyEngine.can(ctx, action, resource)**，禁止散落 `if tenant_id == ...` 判断
5. **跨租户访问只能由 `platform-admin` 走显式特权 API**，普通业务路径必须 `resource.tenant_id == ctx.tenant_id`
6. **CI 防线**：dependency-cruiser/import-linter 检查依赖方向 + grep 检查 `display_name` 是否泄漏到资源命名

### 3.3 命名空间规划（按 tenant_id）

```
ack-cluster/
  ├─ platform-system/         # 平台组件（API、Portal、MLflow、Gravitino、Keycloak、监控）
  ├─ kueue-system/
  ├─ volcano-system/
  ├─ argo/
  ├─ ray-system/
  ├─ tenant-t-0001/           # X-user team 作业、推理、Workspace
  └─ tenant-t-XXXX/            # 未来其他 tenant
```

### 3.4 OSS 路径约定（按 tenant_id）

```
oss://lite-ai-infra/
  ├─ raw/<tenant_id>/<dataset>/...
  ├─ processed/<tenant_id>/<dataset>.lance/
  ├─ embeddings/<tenant_id>/<dataset>.lance/
  ├─ checkpoints/<tenant_id>/<run_id>/
  ├─ models/<tenant_id>/<model>/<version>/
  └─ logs/<tenant_id>/<run_id>/
```

**RAM 策略**：tenant-t-0001 ServiceAccount 仅能访问 `*/t-0001/*` 前缀。

### 3.5 资产 URI（用户视角）

```
统一 URI 协议：gravitino://<tenant_or_alias>.<name>[@<version>]

用户两种用法：
  • 显式 tenant_id：  gravitino://t-0001.v1
  • 别名 "my"：       gravitino://my/v1            ← SDK 自动替换为当前 tenant_id

底层 OSS 路径由 Platform API 通过 Gravitino + Tenant Service 联合解析。
用户从不直接拼 OSS 路径或 tenant_id 字符串。
```

### 3.6 训练镜像契约

```
契约：
  • 入口：/opt/train/entrypoint.sh
  • 必接环境变量：
      DATA_URI, OUTPUT_URI, MLFLOW_TRACKING_URI, MLFLOW_RUN_ID,
      CKPT_URI, RANK, WORLD_SIZE, TENANT_ID
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

- **Gravitino**：数据集 / 模型 / 部署的资产目录，**schema = tenant_id**
- **MLflow**：单次训练的参数/指标/artifact，**experiment 按 tenant_id 分组**
- **衔接**：MLflow 注册的 model artifact URI 反向登记到 Gravitino

### 3.8 Workspace 形态

```
Workspace Pod = StatefulSet（保 PVC）
  ├─ code-server (port 8080)        浏览器 VSCode（OIDC 鉴权 by Keycloak）
  ├─ sshd (port 22)                  本地 VSCode Remote-SSH（key-pair 入 Keycloak attr）
  ├─ ~/workspace                     PVC 持久化
  ├─ /mnt/oss/<tenant_id>/           OSS 通过 ossfs/JindoFS 挂载（仅本 tenant）
  └─ 预装：Python 3.11, uv, Git, 平台 SDK, PyTorch, Ray, Lance

生命周期：
  • 默认 0 GPU；按需 1 GPU（Kueue 配额限制单用户 ≤1）
  • 8h 空闲自动 stop（PVC 保留）
  • 用户重新 start 即可恢复

访问：
  • https://workspace.lite-ai-infra.internal/<workspace-id>/    (Keycloak OIDC)
  • ssh -p <NodePort> user@<workspace-id>.lite-ai-infra.internal
```

---

## 4. 数据流详图

### 4.1 数据准备流（10TB 图文 → Lance）

```
laictl data prepare → Platform API (Keycloak token 校验 → 解析 tenant_id=t-0001)
  → Argo Workflow (拉 RayCluster in tenant ns)
    step-1: ray-data-load  (从 oss://raw/t-0001/ 流式读)
    step-2: data-juicer-ops
    step-3: ray-data-write (写 oss://processed/t-0001/.lance)
    step-4: build-stats    (→ MLflow，experiment="t-0001/data-prep")
  → Gravitino schema=t_0001 注册 dataset (status=ready, schema, version)
  → tear down RayCluster
```

### 4.2 预训练流（1B 多模态 DDP）

```
platform.submit_pretrain(image, entrypoint, data_uri="gravitino://my/v1", output_model="my/multimodal-1b")
  → SDK：从本地 token 缓存 取 OIDC token 注入 Authorization header
  → Platform API
    → Keycloak token 校验 → 解析 tenant_id=t-0001
    → "my" → "t-0001" 替换
    → Gravitino 解析 t_0001.v1 → OSS 路径
    → MLflow 创建 run（tag tenant_id=t-0001）
    → Kueue（LocalQueue=tenant-t-0001）入队
    → Volcano Job in ns=tenant-t-0001
  → 训练 Pod
    env: DATA_URI/OUTPUT_URI/MLFLOW_*/CKPT_URI/RANK/WORLD_SIZE/TENANT_ID
    Lance 流式读 → MLflow log → 30min/epoch 写 ckpt 到 oss://checkpoints/t-0001/<run_id>/
  → 完成
    artifact → oss://models/t-0001/multimodal-1b/v<N>/
    Gravitino t_0001 schema 注册 model version (lineage: dataset)
```

**容错**：节点挂 → Volcano 整组重启 → 自动续训 ≤30min 前 ckpt。

### 4.3 微调流（SFT/LoRA）

```
platform.submit_sft(base_model="gravitino://my/multimodal-1b@v1", data_uri, output_model, use_lora=True)
  → 同上 token + tenant_id 解析
  → Gravitino 解析 base_model → OSS path
  → K8s Job in ns=tenant-t-0001（单节点 1-4 GPU）
  → 预下载 base 到 SSD → LoRA 训练 → adapter 上传 oss://models/t-0001/...
  → Gravitino 注册新版本 + lineage 边
```

### 4.4 推理部署流（vLLM）

```
platform.deploy(model="gravitino://my/multimodal-1b-sft@v1", replicas, gpu_per_replica, endpoint_name)
  → Platform API（token + tenant_id）
    → Gravitino 解析 model → OSS artifact
    → 渲染 K8s Deployment in ns=tenant-t-0001
        initContainer 拉 model
    → Service + Ingress（Ingress hostname 含 tenant_id 前缀，Keycloak OIDC 保护）
  → vLLM 启动 → ready probe → OpenAI 兼容 API
  → 注册 endpoint 到 Gravitino t_0001 schema
  → Prometheus 抓 P95/QPS/GPU util（label tenant_id=t-0001）
```

### 4.5 Embedding 批处理流

```
laictl embed batch --dataset gravitino://my/v1 --model gravitino://my/...-sft@v1 --output my/v1-embeds
  → 部署一次性 embedding 服务在 ns=tenant-t-0001
  → Argo 拉 RayCluster
    Ray Data: lance.dataset → map_batches(call_embedding_api) → write_lance
    建索引: dataset.create_index("vector", "IVF_PQ")
  → Gravitino t_0001 schema 注册 (lineage: source dataset + model)

在线 ANN 查询（推理 Pod 内）：
  ds = lance.dataset("oss://embeddings/t-0001/v1-embeds.lance/")
  ds.to_table(nearest={"column": "vector", "q": query, "k": 10})
```

### 4.6 元数据全景（Gravitino）

```
Catalog: lite-ai-infra
└─ Schema: t_0001                     (= tenant_id, display_name="X-user")
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
| 用户 URI | `gravitino://my/...` 或 `gravitino://t-0001/...`；**禁止 display_name** |
| 平台内部 URI | `gravitino://t_0001.<name>@<version>` |
| OSS 路径 | 用户不直接拼，平台用 tenant_id 解析 |
| 凭证 | K8s ServiceAccount per tenant + RAM Role（OSS 仅 `*/t-XXXX/*` 前缀） |
| Token | 用户 → Keycloak access token → SDK 注入 → Platform API 校验 |
| 失败 | Gravitino + MLflow 同步 status=failed |
| 取消 | 删 K8s 对象 + Argo + 关闭 Ray cluster |

---

## 5. 实施路径（12 周 6 sprint）

### 5.1 时间盘
- 起点：2026-05-08
- 终点：2026-08-01
- Sprint：6 × 2 周
- 缓冲：最后一周不写新代码

### 5.2 角色简称
- **P1**：平台/K8s/训练/推理/Workspace
- **P2**：数据
- **P3**：产品/SDK/CLI/Portal/MLflow/**Keycloak/Tenant**

### 5.3 Sprint 计划

#### Sprint 0（Week 1，05-08 → 05-15）：地基 + Spike + Keycloak

| 负责 | 任务 |
|---|---|
| P1 | ACK 集群（GPU 节点池、网络、ACR） |
| P1 | Volcano + Kueue + KubeRay + Argo Helm 装 |
| P2 | **Spike 1**: Lance on OSS 读写延迟（100GB） |
| P2 | **Spike 2**: Data-Juicer + Ray 在 100GB 子集跑通 |
| P3 | **Keycloak 部署**（StatefulSet + RDS）+ realm/client 初始配置 |
| P3 | Gravitino + MLflow + Postgres 部署 |
| P3 | **Tenant Service v0**（最简：硬编码 t-0001 + Keycloak token 校验中间件） |
| 全员 | spec-kit `/specify` `/plan` `/tasks`，constitution.md（含资源命名约束） |

**出口**：3 个 spike PASS；Keycloak 可登录拿 token；Platform API 能解析 token 出 tenant_id。

#### Sprint 1（Week 2-3，05-16 → 05-29）：训练运行时 + Tenant 注入

| P1 | 训练镜像 train-pytorch-ddp:v1（含 TENANT_ID 环境变量约定） |
| P1 | Volcano Job 模板 + ServiceAccount per tenant + RAM Role |
| P1 | Checkpoint 恢复脚本 |
| P2 | Lance 读取 helper |
| P2 | 公开 baseline 跑通 DDP |
| P3 | Platform API v0：POST /pretrain（含 token 校验 + tenant_id 注入） |
| P3 | SDK v0：submit_pretrain（OIDC device flow login + token 缓存） |

**出口**：手工或 SDK 提交 → 训练在 tenant-t-0001 ns 跑起来；MLflow run 带 tenant_id tag。

#### Sprint 2（Week 4-5，05-30 → 06-12）：数据管线 + Gravitino 多 schema

| P2 | Argo data-prep DAG（按 tenant_id 隔离） |
| P2 | **Data-Juicer 跑 10TB**（关键里程碑） |
| P2 | Lance 索引创建 |
| P2 | Gravitino 注册（schema=t_0001） |
| P3 | URI 解析器（gravitino://my/... → tenant_id 替换） |
| P3 | CLI laictl data prepare/list/describe（含 laictl login） |
| P3 | Tenant Service：成员/角色查询 API |
| P1 | DeepSpeed 镜像 train-deepspeed:v1 |
| P1 | Prometheus + Grafana + DCGM 看板（含 tenant_id label） |

**出口**：raw → 命令一行 → Lance + Gravitino t_0001 schema 可查。监控可见。

#### Sprint 3（Week 6-7，06-13 → 06-26）：SFT + 推理 + Workspace

| P1 | SFT 镜像 + submit_sft API |
| P1 | 推理镜像 serve-vllm:v1 + platform.deploy（按 tenant_id ns） |
| P1 | Workspace Operator + dev 镜像 |
| P1 | Workspace 生命周期 + Keycloak OIDC ingress |
| P2 | Embedding 批处理 Argo Workflow |
| P2 | Lance ANN 在线查询封装 |
| P3 | SDK 全集 + CLI 对应命令 |

**出口**：pretrain → SFT → deploy → 推理 → embedding → ANN 全链路通；Workspace 经 Keycloak 鉴权。

#### Sprint 4（Week 8-9，06-27 → 07-10）：完整租户模型 + Portal + 全量预演 #1

| P1 | Kueue ClusterQueue + LocalQueue per tenant，配额硬限 |
| P1 | RAM Role per tenant（OSS prefix 隔离） |
| P3 | **第二个测试 tenant 接入演练**（不真用，只验证多租户路径全通） |
| P3 | Portal v1（Next.js + Keycloak OIDC） |
| P3 | Portal 列表 + 跨子系统跳转（MLflow/Grafana/Workspace） |
| P2 | Gravitino 跨 schema 搜索 API（仅自己的） |
| 全员 | **X-user team 1B 全量预演 #1** |

**出口**：Portal 可用；架构验证 = 有 2 个 tenant 同时存在但隔离；X-user 独立走完全流程。

#### Sprint 5（Week 10-11，07-11 → 07-24）：硬化 + 性能调优

| 全员 | 处理预演 #1 反馈 |
| P1 | 训练 GPU 利用率调优（≥60%） |
| P1 | 推理 P95 延迟基准 + vLLM 调优 |
| P1 | 抢占恢复演练（≤1h） |
| P2 | Lance 热点路径优化 |
| P2 | Embedding 批吞吐基准 |
| P3 | SDK/CLI 错误信息友好化 + 文档 |
| P3 | Keycloak HA 演练（杀一副本） |
| 全员 | **X-user 全量预演 #2**（达性能目标） |

**出口**：8 + 1 条验收标准全过。

#### Sprint 6（Week 12，07-25 → 08-01）：联调 + 上线 buffer

| 全员 | 仅 bugfix |
| 全员 | 文档收口、监控告警上线、X-user 培训 |

**出口（MVP 验收 08-01）**：X-user team 独立提交 1B 真实预训练。

### 5.4 Hard Deadlines

| 日期 | 里程碑 | 不达标后果 |
|---|---|---|
| 05-15 | Spike 全 PASS + Keycloak 可登录 | 顺延，可能砍 v1 范围 |
| 05-29 | 训练跑通小模型 + tenant_id 注入正确 | 顺延 1 周 |
| 06-12 | 10TB 数据管线 PASS + Gravitino schema=t_0001 | 砍数据集量 |
| 06-26 | SFT/推理/Workspace 三件套通 + OIDC 全链 | 砍推理或 Workspace |
| 07-10 | 全链路预演 #1 + 第二 tenant 接入演练 | **必须达成** |
| 07-24 | 预演 #2 性能达标 | 顺延 buffer 周 |
| **08-01** | **MVP 验收** | **MVP 失败** |

### 5.5 滑窗策略

按"不可砍 → 可降级 → 必砍"分层：
1. **不可砍**：训练运行时、Checkpoint 容错、数据管线、监控、**Keycloak/Tenant Service**（架构基线）
2. **可降级**：推理（单实例无 Ingress）、Embedding 批（10% 数据）、Workspace（仅 SSH）、Portal 美化
3. **必砍优先**：Lineage 自动化 → CLI 高级命令 → 模板镜像数量 → 第二 tenant 接入演练（保留架构能力即可）

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
| D1 | OSS 凭证泄漏 | ServiceAccount + RAM Role per tenant；CI secret scan |
| **D5** | **资源命名混入 display_name 导致泄漏 / 难重命名** | **constitution.md 硬约束；CI 跑 grep 检查（V9 用例）；code review 强制** |

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
| O7 | **tenant_id 与 K8s ns / OSS prefix / Gravitino schema 不一致** | **Tenant Service 统一 reconcile 任务，发现漂移告警** |
| S3 | 人员请假 | 知识备份 |
| S4 | 公司临时插队需求 | constitution 写明 v1 拒绝；老板背书 |
| D2 | 跨租户越权 | OSS prefix RAM 策略 + Gravitino schema RBAC |
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

#### 身份/租户
| 故障 | 恢复 |
|---|---|
| Keycloak 主副本挂 | 第二副本接管（HA） |
| Tenant Service 不可达 | Platform API 缓存 tenant_id 解析（5min TTL）|
| Realm 配置漂移 | IaC 重新 apply |

### 6.4 监控与告警

#### 关键看板
| 看板 | 指标 |
|---|---|
| 集群总览 | GPU util、节点 ready、Pending Pod、OSS 流量 |
| 训练作业 | per-run loss/throughput/GPU util/ckpt 写入（按 tenant_id） |
| 推理服务 | P50/P95/P99/QPS/token-s/GPU mem（按 tenant_id） |
| 数据管线 | Argo 状态、Ray 健康、清洗吞吐 |
| Workspace | 活跃数、GPU 占用、空闲分布（按 tenant_id） |
| 平台自身 | Platform API 错误率、Gravitino/MLflow/PG/**Keycloak** 健康 |
| **租户用量** | **per-tenant GPU 时长、OSS 字节、作业数（v1 仅 t-0001）** |

#### P0 告警
- 训练 ckpt 30min 未写
- GPU 节点 NotReady
- Platform API 错误率 > 5%（5min）
- Gravitino / MLflow / **Keycloak** 不可用（1min）
- OSS 凭证 < 10min 未续
- Volcano / Kueue / Argo controller 挂
- **Tenant Service token 校验失败率 > 10%（2min）**

#### P1 告警
- 推理 P99 > baseline × 2（10min）
- Workspace 空闲 > 8h
- OSS 流量 > baseline × 3
- Kueue 队列积压（30min）

#### 日志栈（详见 ADR-005）

- **栈**：OpenSearch 2.x（StatefulSet 单副本）+ Fluent Bit 3.x（DaemonSet）+ Grafana（OpenSearch datasource）
- **多租户隔离**：Fluent Bit 通过 K8s namespace metadata 注入 `tenant_id` label；index 模式 `logs-{tenant_id}-{date}`；无 label 日志写入 `logs-unlabeled-*` 隔离 index
- **保留**：热数据 14 天本地 PV；超期由定时 job 归档到 `oss://logs/{tenant_id}/{date}/`
- **查询权限**：v1 软隔离（Grafana datasource 默认带 `tenant_id` 过滤）；v2 接 OpenSearch security plugin RBAC 做硬隔离
- **环境差异**：dev 用 docker-compose 单容器；staging/prod 上 StatefulSet（Sprint 1 落地，0b 仅 dev 跑通）
- **故障**：单副本宕机会丢失当时段未落盘日志，RTO 4h（v1 可接受）；v2 上 HA + ILM

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
| V1 | 数据准备闭环 | 10TB raw → Lance + Gravitino schema=t_0001 ready，48h 内 |
| V2 | 1B 多模态预训练 | 3-4 天，GPU util ≥ 60%，loss 单调降 |
| V3 | SFT/LoRA | 24h 内，adapter < 200MB，eval 优于 base |
| V4 | 推理部署 + 调用 | 5min ready，100 QPS 无 5xx，GPU mem 稳定 |
| V5 | 训练容错 | 杀 pod 5min 内恢复，丢失 ≤ 30min |
| V6 | 可观测 | 指标 ≤30s 延迟，P0 告警 5min 内推送 |
| V7 | 多租户落地 | OIDC 登录拿 token；submit 自动注入 tenant_id；第二测试 tenant 不能访问 t-0001 资源 |
| V8 | Embedding 闭环 | 10TB 24h 内，ANN ≤ 500ms |
| **V9** | **资源命名审计** | **`grep -ri "x-user" oss-paths k8s-resources gravitino-schemas mlflow-experiments` 必须为空（仅出现在 display 字段）** |

### 7.3 L2 集成测试

| 测试集 | 内容 | 频率 |
|---|---|---|
| 训练集成 | mini DDP + tenant_id 注入 | nightly |
| 数据管线集成 | 100MB 子集 + Gravitino schema 写 | sprint 末 |
| 推理集成 | 部署 + OIDC 调用 | nightly |
| Workspace 集成 | OIDC 登录 → 创建 → SSH → 删除 | sprint 末 |
| **多租户集成** | **创建 tenant t-test → 提作业 → 验隔离 → 删除** | **sprint 末** |
| Platform API | 全 endpoint pytest（含 token 校验失败路径） | 每 PR |

### 7.4 L1 单元测试范围

| 模块 | 重点 |
|---|---|
| URI 解析器 | gravitino:// + my/ 别名、错误格式 |
| **Tenant Service** | **token 解析、tenant_id 缓存、display_name 查询** |
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

### 7.6 验收判定流程

```
Sprint 6 (07-25 起)
  Day 1-3: 平台跑全部 V1-V9 打分
  Day 4: X-user team 自跑反馈
  Day 5: 联席验收会议
    全 Pass → MVP 达标，08-01 起跑
    Partial → 平台决定阻塞与否
    Fail → hot fix 或推迟 + 通知老板
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
| **Platform API / SDK / CLI** | 容器化 | 容器化 | 本地 `uvicorn` / `pip install -e .` 热重载 |

### 8.3 配置与密钥分层

```
config/
  ├─ base.yaml                 # 跨环境共享（Gravitino schema 模板、URI 协议、tenant_id 格式）
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
  • SDK/CLI：pip install -e .，单测 + 集成测试
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
| Keycloak 多 realm | dev realm 预导入，1 个 admin + 1 个 tenant 用户 | dev 简化 |
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
| Tenant | 平台多租户的最小单元（一个团队 = 一个 tenant） |
| tenant_id | 不透明租户标识（如 `t-0001`），用于所有资源命名 |
| display_name | 租户的人类可读名（如 "X-user"），仅用于 UI/日志 |
| X-user team | v1 平台的首个真实租户（display_name=X-user, tenant_id=t-0001） |
| Lance | 列存数据格式，原生支持向量列 + ANN（开源） |
| Gravitino | Apache 开源元数据 catalog（schema = tenant_id） |
| MLflow | 实验跟踪服务（experiment 按 tenant_id tag） |
| Keycloak | 开源 OIDC IdP，承担身份认证 + 租户/用户/角色管理 |
| Tenant Service | Platform API 内置模块：token 校验、tenant_id 解析、租户元数据 |
| Data-Juicer | 阿里多模态数据清洗工具，跑在 Ray |
| Volcano | K8s 批处理调度器（gang scheduling） |
| Kueue | K8s 队列 + 配额引擎 |
| KubeRay | Ray on K8s operator |
| code-server | 浏览器版 VSCode（开源） |
| Workspace | 用户开发环境 Pod（code-server + sshd + tenant_id 隔离） |

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
