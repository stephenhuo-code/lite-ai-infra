# S1 设计:数据管线 + 元数据 + 服务化(一人团队修订版)

- 日期:2026-06-11
- 状态:已与 owner 确认(brainstorming 逐节通过)
- 相关:design spec §5.3 Sprint 1 / §8.8;ADR-014(S0 出口① 移交 S1 门禁);constitution 全文;S0 交付(`2026-06-10-s0-dod-status.md`)

---

## 0. 修订前提(与原 spec S1 的差异及依据)

| 原 spec 假设 | 实际 | 本设计处置 |
|---|---|---|
| P1/P2/P3 三人并行 | **一人 + Claude** | 单线程排期,14 个工作日(原 10),S2 起点顺延(v1 交付日后移,S2 计划时走 ADR 记录) |
| S0 ops 轨道已部 ACK/Argo/Gravitino/MLflow | 一项未部 | 最小云档:2 台按需 ECS + OSS;Argo/ACK 推 S2;Gravitino docker 单容器 |
| 数据集就绪 | 公开数据集,未下载 | W1 云端直拉(ECS→OSS 内网),候选 LAION 子集,fallback CC3M/COCO 混合 |
| — | ADR-014:出口① 是 S1 第一周入口门禁(06-17 硬时限) | W1 D1–3 全部让位门禁,不过门禁不开工管线 |

预算:A 档(1 小 ECS Keycloak + 1 大内存 ECS 按需启停 + OSS 100GB+,全程数百元)。

## 1. 范围与出口

**保留全部 spec S1 出口,仅 Dev Workspace 一项降级:**

| # | 出口 | S1 形态 | 验收 |
|---|---|---|---|
| ① | 100GB 一行命令清洗(多模态)→ Lance | 完整:DJ+Ray on ECS → Lance on OSS 隔离路径 | 一行命令跑完 100GB,Lance 可读 |
| ② | Gravitino schema 可查 | 完整:docker 单容器,schema `e_0001_g_0001` | API 查到 schema/表 + owner/scope 属性 |
| ③ | 薄 can() 企业隔离 | S0 已交付;S1 接入管线入口与两个新服务 | 隔离用例过(单测+集成) |
| ⑤ | 契约 SDK/CLI 可调 | 完整:OpenAPI → 生成 client + `laictl`(prepare/list/describe) | CLI 三命令打真服务成功 |
| 新 | **服务化**(spec S1 P1 项) | data-pipeline-service + metadata-service,契约先行 | 契约↔实现一致,经 gateway can()+audit |
| ④ | Dev Workspace | **唯一降级**:docker code-server 半天版(stretch,W3 D4);K8s Pod 版推 S2 | 可起即过(stretch,不阻塞 DoD) |

明确不做(S2/vN+):Argo DAG、ACK/K8s、Gravitino HA、MLflow 接入、Embedding/ANN、前端、Enterprise Provisioner。

## 2. 架构

```
laictl CLI ──┐
             ├─→ gateway(S0:token→can()→audit)
SDK(生成) ──┘        │
              ┌──────┴──────────┐
   data-pipeline-service   metadata-service        ← 新增 FastAPI 服务
   (submit/status/list)    (datasets/schemas 查询)
        │                        │
   pipelines/data_prep      Gravitino(docker@ECS)
   (DJ+Ray 批作业@大ECS)         │
        └──→ Lance on OSS(oss://…/e-0001/g-0001/…)←─ 注册
```

**关键决策:**

1. **契约先行**:`contracts/openapi/data-pipeline.yaml` + `contracts/openapi/metadata.yaml` 先写 → datamodel-codegen → 服务实现。复用 S0 任务 7/10 全套机制(oasdiff warn 门禁 + codegen freshness 门禁自动覆盖新契约)。契约 0.x,字段从宽(分页/过滤/状态),为 S2 前端原型反馈留加法余地。
2. **管线与服务解耦**:`pipelines/data_prep` 独立包,可 CLI 直跑;服务只做提交/查状态薄壳(S1 进程内/subprocess 调度,Argo 推 S2)。服务挂,管线不挂。
3. **分层扩展**:import-linter 由 `services → libs` 扩为 **`services → pipelines → libs`**;`pipelines` 不得 import `services`。
4. **纪律延续**:所有 mutation 经 `can()`(宪法 §2.4 唯一出入口)+ 审计(best-effort);资源命名只有不透明 ID(护栏已在 CI)。
5. **运行时形态**:两服务与 gateway 同进程组部署可接受(S1 单机 uvicorn 多 app 或单 app 多 router 均可,实现期定,以契约边界为准——服务边界=契约边界,而非进程边界,符合宪法 §4 对 v1 的容忍)。

## 3. 数据流与隔离(宪法 §1 落地)

1. **取数**:公开图文数据集(首选 LAION-400M 子集,fallback CC3M/COCO 混合;W1 D1 实测可达性后定)→ ECS 内网拉 → `oss://<bucket>/e-0001/g-0001/raw/<dataset>/`
2. **清洗**:DJ+Ray(单机 Ray cluster on 大内存 ECS),真实算子集:图文去重、CLIP 相似度过滤、图像尺寸/比例、文本长度/质量;分片 + spill 参数由 Spike 2 的 OOM 边界结论喂入
3. **落盘**:Lance → `oss://<bucket>/e-0001/g-0001/processed/<dataset>/`(列含 image/text/元特征;列设计实现期随 Spike 1 结论微调)
4. **注册**:Gravitino schema `e_0001_g_0001`,表属性带 owner/scope
5. **全程隔离**:路径/schema 仅不透明 ID;跨企业访问被 `can()` 拒(集成用例覆盖)

## 4. 错误处理与测试

延续 S0 两层(unit 零依赖 / `-m integration` 真依赖):

- **单元**:管线算子配置、分片策略、Lance 路径构造、两服务 handler(`x-test-claims` seam + MemoryAuditSink,seam 默认关纪律不变)
- **集成**:真 MinIO(Lance 写读)、真 Gravitino(dev docker-compose 增加容器:注册+查询)、真 Keycloak(沿用)
- **管线容错**:分片级重试;失败分片记录可重跑(幂等:同输入分片重跑覆盖同输出路径);审计 best-effort
- **E2E 验收**:100GB 一行命令完跑 + `laictl data list` 查到 + Gravitino API 查到 schema + 跨企业访问 403

## 5. 时间线(14 个工作日,从 2026-06-12 起)

| 时段 | 内容 | 里程碑 |
|---|---|---|
| W1 D1–3 | **ADR-014 门禁**:云最小环境(runbook §1–3)+ 数据集云端下载 + 数据 Spike 1/2 真跑 + Spike A 复验/Spike C → 结论回写 ADR-010/spike 文档 | **06-17 硬时限;不过不开工** |
| W1 D4–5 | `pipelines/data_prep` TDD:DJ recipe 生产化 + Lance writer(隔离路径) | |
| W2 D1–3 | 100GB 端到端一行命令;Gravitino 部署 + 注册 + 查询 | **出口①②** |
| W2 D4–5 | 两个 OpenAPI 契约 + codegen;data-pipeline-service TDD | |
| W3 D1–2 | metadata-service TDD;SDK 生成 + `laictl` 三命令 | **出口⑤ + 服务化** |
| W3 D3 | 集成全绿 + E2E 验收 runbook + code review(requesting-code-review) | DoD |
| W3 D4 | buffer / stretch:code-server 半天版(出口④ 降级形态) | |

**风险与触发动作**:W1 门禁被卡(云/数据集)→ 按 ADR-014 决策 3 当场触发顺延评估,整体顺移,不带病推进。Spike 出"降级"结论 → fallback 已预设(Lance 延迟不达 → JindoFS/本地缓存层;DJ OOM → 收缩分片 + spill),W1 D4 起按降级形态实现。

## 6. 边界与 S2 交接备忘

1. **S2 前端原型先行**:数据域前端的**低保真原型必须在 S2 spec 之前/之中**完成(brainstorming visual companion)——前端是契约的第一个消费者,原型驱动契约修订(S1 契约 0.x 留了加法余地)。高保真视觉稿放 spec 后。
2. **S2 必须分阶段**:S2a(10TB 放大 + Gravitino HA)→ S2b(Embedding/ANN + V8 斜率)→ S2c(前端 + Provisioner),每段独立验收;S2 时长按一人现实重排,与 v1 交付日后移一起走 ADR(宪法 §7)。
3. S1 出口①②⑤ 的产物(管线包/契约/SDK)即 S2a/S2c 的直接输入;Argo 化与 K8s 化在 S2a 评估。

## 7. DoD(S1 签收门禁)

- [ ] ADR-014 门禁关闭(数据 Spike 1/2 结论 + Spike A 复验/C 回写)
- [ ] 出口①②⑤ + 服务化验收命令实测通过(贴输出)
- [ ] 单元 + 集成全绿;import-linter(含 pipelines 层)+ §8 护栏 + codegen freshness 绿
- [ ] code review 过
- [ ] CI 远端绿
- [ ] go/no-go 签字

## 8. 补遗:用户自定义管线的三层开放路线(2026-06-12,owner 问答沉淀)

**原则:用户代码永不进平台进程;平台握住"信封"(can() 授权、审计、隔离路径、Lance 产物格式)。**

| 层级 | 形态 | 时点 | 安全边界 |
|---|---|---|---|
| 1. 配方自定义 | API 请求体传 DJ `process` 算子列表(100+ 内置算子,配方是数据非代码) | **Plan 2 已支持**(`build_recipe(process=…)` 注入口;服务化暴露 = Plan 5) | 无代码执行,天然多租户安全 |
| 2. BYO-Step 容器 | 用户代码打容器镜像,作为平台 DAG 中一步;平台定 IO 契约(挂载 jsonl/图片目录进出);跑在企业隔离 ns,只挂本组 raw/ | **S2a(配 Argo)**;`runner` 的 `dj_fn` seam 从 subprocess 换 Argo 提交即可 | 容器隔离 + ns 隔离 + 路径最小挂载;Lance 写入仍平台执行 |
| 3. 自定义 DJ 算子 / 全自定义 DAG | 用户上传 Python 算子 / 自编排 DAG | **vN+**(需逐企业 Ray 集群、镜像扫描、配额硬限的沙箱方案) | 待设计;开发环境=Dev Workspace(S2c) |

S2 spec 编写时:层级 2 的 IO 契约与 `custom_step` API 形态进 S2a 范围;层级 3 仅记 backlog。

## 9. 服务化拆解修订(2026-06-13,owner 决策)

**起因**:Plan 2 采用了"库 + 手写 CLI 先行,契约/服务后补"的序——与 API 优先(§3.0.2 契约先行)相悖。`pipelines/data_prep` 作为**服务内部实现**完全复用(已云上验收),需纠正的是拆解单位与顺序:**按服务拆,每服务契约优先**。

**owner 决策**:
1. **identity-org-service 严格独立拆分**(不折叠进 gateway);gateway 回归纯 BFF(token 校验 + 路由/聚合)。
2. **手写 `python -m pipelines.data_prep` 降级为 ops/debug 后门**;产品级 CLI/SDK 由契约生成、经 HTTP 调服务。

### 9.1 服务职责边界(契约即边界)

| 服务 | 契约 | 拥有 endpoint | 后端实现 | 包路径 |
|---|---|---|---|---|
| api-gateway / BFF | (聚合) | token 校验 + 路由 + 聚合 | — | `services/gateway/` ✅ |
| identity-org-service | `identity-org.yaml` | `GET /v1/me/orgs` | Keycloak claim 解析(`libs/identity`) | `services/identity_org_service/`(新,从 gateway 迁出) |
| metadata-service | `metadata.yaml`(新) | `GET /v1/datasets`、`/v1/datasets/{name}`、`/v1/schemas` | Gravitino(docker) | `services/metadata_service/`(新) |
| data-pipeline-service | `data-pipeline.yaml`(新) | `POST /v1/data/prepare`、`GET /v1/data/jobs/{id}` | `pipelines/data_prep.run_prepare`(✅已建) | `services/data_pipeline_service/`(新) |

边界铁律:**"列/查数据集"归 metadata-service(它拥有 catalog);"跑管线"归 data-pipeline-service**。v1 可同进程共部署,但契约/包/`/docs` 各自独立。`pipelines/data_prep` 与 `libs/` 保持为实现层(分层 `services → pipelines → libs` 不变)。

### 9.2 每服务的契约优先全循环

`契约(OpenAPI 3.1)→ datamodel-codegen 生成模型 → FastAPI app(模块级 app + /docs)→ 实现(包 libs/pipelines)→ 挂 gateway 后 → 漂移守卫(运行时 openapi.json ⊆ 契约,CI)`。

### 9.3 计划序(编号 = 实际计划文档,owner 06-14 统一口径 A)

> 编号以 `docs/superpowers/plans/` 里**实际文档**为准(可数、文件名一致)。早先草拟的"5 个计划"序里 Plan 3(脚手架)+ Plan 4(identity-org)被**实际 Plan 3 文档合并交付**,故整体回退一位。

| 计划(=实际文档) | 内容 | 出口 | 状态 |
|---|---|---|---|
| **Plan 3:服务脚手架 + identity-org-service + gateway 反代壳** | 统一 FastAPI 模板(/docs)+ `make api-docs` + 漂移守卫 CI;identity-org 从 gateway 迁出独立;gateway 改纯反代壳 | swagger 能力 + 服务化① | ✅ 已合并 |
| **Plan 4:metadata-service** | `metadata.yaml` 契约先行 + Gravitino docker 后端 + 注册/查询 + 集成 | **出口②** | ✅ 已合并 |
| **Plan 5:data-pipeline-service** | `data-pipeline.yaml` 契约先行 + 包 `run_prepare`(submit→job_id + 查状态)+ 集成 | 服务化 | ⏳ 下一个 |
| **Plan 6:生成式 SDK/CLI** | 由契约生成 client + `laictl data prepare/list/describe`(调服务 API,OIDC device flow) | **出口⑤** | ⏳ |
| stretch | Dev Workspace docker 版 | ④降级 | ⏳ |

> 手写 CLI 留作 ops 后门(`pipelines/data_prep/__main__.py` 标注非产品入口);产品 CLI 由 Plan 6 契约生成。
