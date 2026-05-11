# ADR-005: 日志栈选型 — OpenSearch + Fluent Bit + Grafana（自建）

- 状态：Accepted
- 日期：2026-05-10
- 决策人：X-user team（P1/P2/P3）
- 相关：design doc §1.1 / §1.2 / §3 选型表 / §8.2 多环境差异表

## Context

原 design doc 选用阿里云 SLS（托管日志服务）。复盘后决定改自建：

- **厂商绑定风险**：SLS API、查询语法、索引结构与阿里云强耦合，跨云迁移（未来可能上 AWS / 自建 IDC）成本高
- **成本可控**：v1 单租户 + 低日志量，托管 SLS 的按量计费在小规模下并无价格优势
- **与监控栈复用**：design doc §6.4 已规划 Grafana 作为监控可视化，希望日志查询复用同一 dashboard 平台，避免引入第二套 UI（Kibana / SLS 控制台）
- **多租户隔离自主可控**：v1 起即多租户的硬纪律下，日志按 `tenant_id` 隔离的 index/RBAC 策略需要自定义，托管服务的隔离粒度受限

## Decision

采用 **OpenSearch 2.x + Fluent Bit 3.x + Grafana（OpenSearch datasource）** 三件套，自建部署。

### 选型理由

| 候选 | 决策 | 依据 |
|---|---|---|
| OpenSearch 2.x | ✅ 选 | Apache 2.0 license 干净；AWS 主导社区活跃；与 ES 7.10 API 兼容；OSS 镜像免费 |
| Elasticsearch 8.x | ❌ 拒 | Elastic License 2.0 对托管/SaaS 场景有限制，长期风险 |
| Elasticsearch 7.10 OSS | ❌ 拒 | 已停更，安全补丁不再 |
| Fluent Bit | ✅ 选 | 资源占用低（C 实现）；K8s DaemonSet 主流；filter 链支持 K8s metadata 注入 |
| Filebeat / Vector | ❌ 备选 | Filebeat 与 Elastic 绑定；Vector 学习成本与 v1 收益不匹配 |
| Grafana（OpenSearch datasource） | ✅ 选 | 与现有 Grafana 复用，单 dashboard 平台；datasource 原生支持 |
| Kibana / OpenSearch Dashboards | ❌ 拒 | 与 Grafana 重复，增加运维和用户认知负担 |

### v1 部署形态

- **OpenSearch**：StatefulSet 单副本（与 Keycloak v1 单副本对齐，参见 ADR-002）
  - 本地 PV 存储，14 天热数据保留
  - 故障恢复 RTO 目标 = 4h（v1 可接受）
  - v2 上 HA + 多 data node + ILM 策略
- **Fluent Bit**：DaemonSet，全节点采集
  - 通过 K8s metadata filter 从 namespace 解析 `tenant_id`（namespace 命名规则参见 spec 002-resource-naming-policy）
  - 注入字段：`tenant_id`, `pod_name`, `container_name`, `namespace`, `node`
  - Output：写入 OpenSearch index pattern `logs-{tenant_id}-{YYYY.MM.DD}`
- **Grafana datasource**：每个 tenant 配一个 datasource，query 强制带 `tenant_id` 过滤；v2 接 OpenSearch RBAC 做硬隔离

### 多租户隔离策略

| 隔离维度 | v1 机制 | v2 加强 |
|---|---|---|
| 写入 | Fluent Bit 强制注入 `tenant_id` label，无 label 的日志丢到 `logs-unlabeled-*` 隔离 index | OpenSearch ingest pipeline 双重校验 |
| 索引 | `logs-{tenant_id}-{date}` per-tenant 分 index | 同 |
| 查询 | Grafana datasource 软隔离（query 默认带 `tenant_id` 过滤） | OpenSearch security plugin RBAC，按 role 限定 index pattern |
| 归档 | 14 天后由定时 job 导出 → `oss://logs/{tenant_id}/{date}/` | ILM 策略自动化 |

### dev / staging / prod 形态

- **dev**：docker-compose 单容器 OpenSearch + Fluent Bit；保留 7 天；本地卷
- **staging / prod**：StatefulSet 单副本 + 本地 PV + 每日快照到 OSS；保留 14 天
- staging/prod 部署延到 **Sprint 1**（0b 仅 dev 跑通），P2 0b 容量已饱和

## Consequence

### 正面

- 无 license 风险，无厂商绑定，跨云迁移成本低
- 与 Grafana 复用，团队仅维护一套 dashboard 平台
- 多租户隔离机制自主可控，与"v1 起即多租户"硬纪律一致
- v1 启动成本低（单容器即可），v2 平滑扩为 HA

### 负面

- 多一个 StatefulSet 运维负担：单副本宕机会导致**当时段日志丢失**（已落盘的不丢）→ P2 需在 Sprint 1 加运维 runbook
- v1 多租户隔离是**软隔离**（label + Grafana datasource filter），管理员误操作仍可能跨 tenant 查询 → 写进风险表 + v2 上 OpenSearch RBAC
- OpenSearch StatefulSet 资源占用（内存默认 1-2GB heap）需在 staging/prod 容量规划中预留
- 冷归档脚本（14 天 → OSS）需自研一个定时 job，v1 可先用 cronjob + 简单 elasticdump

### 中性

- Fluent Bit 的 K8s metadata filter 需要 ServiceAccount 读 namespace label，新增一个最小权限 ClusterRole

## 后续动作

- [ ] Sprint 0a 0a-10：dev 环境 docker-compose 跑通 OpenSearch + Fluent Bit，验证 `tenant_id` 注入（owner: P2）
- [ ] Sprint 1：staging/prod StatefulSet 部署 + 冷归档脚本（owner: P2）
- [ ] Sprint 1：风险表新增 "OpenSearch 单副本日志丢失" + "v1 软隔离误查询" 两条（owner: P2）
- [ ] v2：OpenSearch RBAC + ILM + HA（owner: 待定）
