# Design — catalog-driven 数据集模型(一等条目 + 血缘)+ 管线从 catalog 读取

> HOW。需求见 [spec.md](./spec.md)。地基决策落 **[ADR-023](../../../adr/ADR-023-catalog-driven-datasets.md)(Accepted)**(catalog-driven 数据集 + 血缘;扩展 [ADR-016](../../../adr/ADR-016-gravitino-tenancy-mapping.md) 的 fileset 语义;执行并改口径 [ADR-018](../../../adr/ADR-018-data-pipeline-job-scheduling.md) 的 S2a)。**引用既有家、不复制**。

> **as-built(2026-06-24,已实现并合并 main)**:① 归属改 **owner 模型([ADR-024](../../../adr/ADR-024-owner-based-dataset-ownership.md))**——归属真相源 = `owner_user`(=上传用户 sub),**`owner_group` 不再参与归属/授权**(group 退为访问/审计维度,留 Cerbos v2);OSS 路径 `e-XXXX/{user}/{raw,processed}/…`(不再按 group)。② **scheme 二元性**:lance 读写 `s3://`、Gravitino fileset location 记 `s3a://`(HCFS),注册端点写 Gravitino 前转 scheme。本文下方旧"owner_group"表述以此为准更新。

## 架构与隔离

### 真相源:catalog(Gravitino fileset)
沿用 [ADR-016](../../../adr/ADR-016-gravitino-tenancy-mapping.md):企业=metalake(`e_XXXX`)、catalog=`data`、schema=`datasets`。**本设计在该 schema 下,让每个 fileset 表达一个"一等数据集"**,新增三个 fileset properties:
- `kind`:`raw` | `processed`(生命周期/能否被当前管线消费)
- `format`:`webdataset` | `lance`(存储格式)
- `derived_from`:来源数据集名(血缘;processed 必填,raw 无)

既有 properties 保留:`owner_user`(**归属真相源**,=上传用户 sub)、`scope`、`location`(fileset storageLocation,记 `s3a://`)。`owner_group` 保留为审计属性、**不参与归属/授权**(group 访问 → Cerbos v2,ADR-024)。

### 三条关键路径
```
注册(显式)        管线读(catalog-driven)              注册派生
─────────────     ──────────────────────────────     ─────────────
upload→OSS         prepare(dataset 名)                作业成功→显式注册 processed
  │                  │ data-pipeline 服务带用户 bearer    │
显式注册 raw         │  调 metadata GET 数据集 → can() 校验 │ location=作业产出 Lance(服务端钉死前缀内)
  │ location=身份钉死  │  → 返回 location                   │ derived_from=输入数据集
  ▼                  ▼  按 location 下载 tar → DJ → Lance  ▼
fileset(kind=raw)   (管线不再猜路径)                    fileset(kind=processed, derived_from=...)
```

### 隔离不变式(宪法 §1.6 / ADR-020 范式)
- **注册 location 服务端钉死 = 本轮新增逻辑(非"沿用")**:现状注册端点(`app.py` register)**直接用 `body.location` 建 fileset、从不钉死**——ADR-020 钉死只落在**上传**端点。本轮**给注册端点新增**:raw 省略 location → 服务端用 `DatasetPaths(bucket, enterprise_of(ctx), group, dataset).raw_prefix` 算(eid/gid 来自 ctx);processed 给定 Lance URI 须落在 `DatasetPaths(...).processed_uri` 的 caller 前缀内(eid/gid 同样来自 ctx,非请求体)。客户端**不能**指任意 location。
- **管线读 catalog 经 metadata `can()`**:data-pipeline 解析位置时,带**调用者 bearer** 调 metadata 的"取数据集"读端点;metadata `can(dataset.read)` 不通过则拒 → 管线拿不到位置 → 隔离不可绕过。
- **信任链(为何管线信 catalog 的 location 安全)**:catalog 的 location **只在注册闸门写入、且服务端钉死** → 管线读时可信;叠加读经 `can()`。**此不变式依赖"location 只在注册时钉死写入";若将来开放 location 客户端可改(外部数据集 import),即破,须重审。**
- 细粒度/跨组共享发现 = **Cerbos(v-next)**,本轮 `can()` 维持现状(企业硬隔离 + 同组)。

## 数据模型 / 契约
### fileset properties(Gravitino)
| property | 值 | 不变量 |
|---|---|---|
| `kind` | raw / processed | 必填;管线输入须 `kind=raw`(v1) |
| `format` | webdataset / lance | 必填;raw→webdataset,processed→lance |
| `derived_from` | 来源数据集名 | processed 必填,raw 不设 |
| `owner_user`/`scope`/`location` | owner=上传用户(ADR-024)| location 服务端钉死,记 `s3a://`;`owner_user` 为归属真相源 |
| `owner_group` | 审计属性 | 保留但**不参与归属/授权**(group 访问→Cerbos v2) |

### 对外契约(`contracts/openapi/metadata.yaml` + `data-pipeline.yaml`,契约先行 §3.0.2)
- `RegisterDataset` 增 `kind`(必)、`format`、`derived_from`(processed 必);**`location` 改为服务端可省/校验**(raw:省略→服务端按身份算;processed:给 Lance URI,服务端校验前缀)。
- `Dataset`(读模型)增 `kind`/`format`/`derived_from` 输出(读 null-safe)。
- 新增 metadata **内部读端点**(或复用现有 `GET …/datasets/{name}`)供 data-pipeline 解析 location;经 `can()`。
- `data-pipeline` 的 `PrepareJobRequest`:源由 `tar_dir`(required,弃用)改为 **`source_dataset`(数据集名)**;服务端解析 location。
- **契约变更策略 = 直接破坏性改(owner 拍;v1 未 GA、无外部消费者)**:`RegisterDataset.location` required→可选+服务端控制、`PrepareJobRequest.tar_dir` 删→`source_dataset`,均为破坏性变更。**同 PR 改全部内部消费者**(`worker.py`/`runner.PrepareRequest` 的 `tar_dir` 引用)+ **更新 oasdiff 基线/豁免**(否则 CI §8 破坏性检查红)。**本策略改 [ADR-018](../../../adr/ADR-018-data-pipeline-job-scheduling.md) 原"加法收紧"口径为"替换",已在 [ADR-023](../../../adr/ADR-023-catalog-driven-datasets.md) §8 留痕**。
- 具体 schema diff 在 plan 落地;**契约改完跑 `make gen` + oasdiff(更新基线)**。

### 状态/血缘
- 数据集生命周期:`raw`(注册后)→ 作业 → `processed`(派生注册)。每个都是独立条目;processed 经 `derived_from` 链向来源 → 形成血缘 DAG(v1 单跳;多跳=二次处理 v-next)。

## 流程(端到端)
1. **bootstrap(一次性)**:为企业建 metalake + catalog(`data`,OSS-fileset 形态,带 s3 配置)+ schema(`datasets`)。显式命令/脚本(provisioner-lite),**非注册时惰性**。空企业浏览 → metadata 列表对 404 返空(spec FR-006)——**注:现状 `list_ds` 不 catch 404、空企业会 500,本轮要补此容错**(非现状)。
2. **上传**:沿用现有 presigned 直传(ADR-020),raw 落 `…/raw/{dataset}/`。
3. **显式注册 raw**:用户点注册 → metadata 建 fileset(`kind=raw, format=webdataset, location=身份钉死 raw_prefix, owner=…`)。
4. **创建作业(catalog-driven)**:用户选 `source_dataset` → data-pipeline 服务带 bearer 调 metadata 取该数据集 location(can() 校验,且须 `kind=raw`)→ 写入 JobSpec → worker。
5. **管线**:worker 用解析到的 OSS location → 下载 `.tar` 到本地(复用本计划同期的 `fetch_oss_tars`)→ `wds_to_jsonl` → DJ → 写 Lance 到 `…/processed/{out}.lance`。
6. **显式注册 processed**:作业成功后用户注册产物 → metadata 建 fileset(`kind=processed, format=lance, location=Lance URI(校验前缀), derived_from=source_dataset`)。**`num_samples` 取自作业结果 `rows_written`(管线权威,用户禁填)——遵 [ADR-008](../../../adr/ADR-008-dataset-metadata-authority.md)"Layer-1 字段由管线写";用户仅触发注册**。
7. **浏览**:数据集页 + 数据目录页显示 kind/format/血缘;创建作业从已注册数据集选源(spec US4)。

## 授权 / 安全 / 红线
- 注册/读/作业**唯一授权出入口** = `can()`(宪法 §2.4)。本轮不改 `can()` 规则。
- raw location 与 processed location **服务端钉死/校验前缀**(ADR-020 C-1 范式),客户端不能指任意位置。
- **pipeline→metadata 读 = 本轮新增基建(承重墙,非现成,首任务/探针)**:现状 data-pipeline **无 HTTP 客户端**、`Context` **不带 token**、worker 是 **detached 子进程无 bearer**。故需新建:① 在 prepare **handler** 捕获入站 bearer(`context_from_request` 现读了 authz 但不暴露,需加 seam)② 一个 metadata 只读客户端。**location 解析必须在 submit 时的 handler 完成**(那里有 bearer + can()),把解析出的 location 写进 `JobSpec` 交 worker——**worker 无 bearer,不能在 worker 解析**。这是新增运行时 HTTP 依赖 pipeline→metadata(非 import,不破 `.importlinter`)。bearer 捕获 + metadata client + submit 时解析 = **Plan 首任务,实测钉死(DoR#4 探针)**。
- 密钥沿用 env-config 单一源(阶段 2);metadata 因建 OSS-fileset catalog 需 OSS 配置(纳入 `SERVICE_ENV_KEYS[metadata]`)。

## NFR
- **dev/prod parity**:catalog/OSS 走 `libs/audit/oss_audit.py:oss_boto3_config`(按 endpoint 自适配);本地 MinIO、阿里云 OSS 同一路径。
- **兼容**:既有 fileset(无 kind/derived_from)读路径 null-safe——`kind=None` 显示「未知/—」,**不臆断为 processed**(防把无 kind 的老 raw 误显示成 processed 误导用户跑管线;与 Edge Case「已处理当原始跑→拒」一致),不崩。
- **规模**:列表沿用 ADR-016 "list 名 + 逐个 get + can() 过滤"(v1 规模可忽略)。
- **CI**:不破现状(FR-008);新单测纳入 pytest;契约破坏性检查跑。
- **部署拓扑**:本轮本地;catalog bootstrap 命令将来并入 S2c provisioner。

## 待探查 / 推迟(DoR #4)
- **探针(Plan 首任务,实测钉死)**:**bearer 传播 + pipeline→metadata 解析链**——证实"prepare handler 能捕获入站 bearer → 调 metadata 读端点(can() 校验)→ 拿到 location → 写进 JobSpec"这条新基建在本地真跑通(承重墙,C-1)。决策规则:跑通则按此实现;若 bearer 捕获/转发受阻,退化方案 = 在 handler 用 ctx 直接查(仍 submit 边界、仍 can()),记 RESULTS。
- **已实测可复用(无需探针)**:Gravitino fileset properties / create_fileset / ensure_* 已在仓库使用;OSS 下载用 boto3(同期 `fetch_oss_tars`);`DatasetPaths.raw_prefix/processed_uri` 现成。
- **显式推迟(v-next,理由见 spec Out)**:Lance→中间格式 ingest(二次处理)、多 catalog/数据域、跨组共享发现(Cerbos)、Organizations。

## 验收 / 测试策略
- **单元**:metadata 注册(kind/format/derived_from 写入 + location 身份钉死 + 重复拒 + 列表 404→空 + 读 null-safe);data-pipeline 作业(source_dataset → 解析 location 的 seam,不存在/不可读 → 错);前端(注册按钮、CreateJob 选源、数据集页显示 kind/血缘)。
- **集成/手动**(对应 SC-001~008):owner-readable runbook —— coco 一小片:上传 → 显式注册 raw → 创建作业(选源,不填路径)→ 管线从 catalog 读跑成功 → 注册 processed(带血缘)→ 两条目在数据集/数据目录页可见,格式/血缘正确。
- **门禁(SC-007)**:`make gen && make lint && uv run pytest -q` 全绿 + 前端 vitest 绿;契约破坏性检查过。
- **DoD**:runbook 全过(owner 可读)+ 门禁全绿 + 隔离负例(指别人位置被拒、读不可读数据集被拒)有测试。

## 关键决策留痕
- **[ADR-023](../../../adr/ADR-023-catalog-driven-datasets.md)(Accepted)**:catalog-driven 数据集 + 一等条目 + 血缘 + 管线读 catalog + 契约直接破坏 + num_samples 管线权威 + derived_from 名引用(v1);**否决方案**:① 约定读(管线猜 OSS 路径)—— 不可扩展到非约定位置、catalog 不成真相源;② 注册时惰性建 catalog —— 语义不纯,迁 provisioner;③ raw 不进 catalog(仅 processed)—— 无法 catalog-driven、无血缘起点;④ num_samples 用户填 —— 违 ADR-008。
- 扩展 [ADR-016](../../../adr/ADR-016-gravitino-tenancy-mapping.md)(fileset 增 kind/format/derived_from,仍"group 作属性非 namespace");执行 [ADR-018](../../../adr/) S2a;隔离沿用 [ADR-020](../../../adr/ADR-020-dataset-upload-mechanism.md) 服务端钉死范式。
