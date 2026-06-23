# ADR-023: catalog-driven 数据集模型(一等条目 + 血缘)+ 管线从 catalog 读取

- 状态:**Accepted(2026-06-23,owner 拍板)**
- 决策人:owner
- 相关:扩展 [ADR-016](./ADR-016-gravitino-tenancy-mapping.md)(fileset 语义)、执行并**改口径** [ADR-018](./ADR-018-data-pipeline-job-scheduling.md)(S2a tar_dir)、提前交付并调和 [ADR-008](./ADR-008-dataset-metadata-authority.md)(lineage/Layer-1 权威)、沿用 [ADR-020](./ADR-020-dataset-upload-mechanism.md)(服务端钉死)。spec/design:`docs/superpowers/plans/2026-06-23-catalog-driven-datasets/`。

## Context
现状数据集是"隐式约定":管线按命名约定猜 OSS 路径、raw 不进目录、只有 processed 才作为 fileset 进 catalog。要让 **catalog(Gravitino)成为数据集位置的唯一真相源**:每个数据集(raw/processed)都是一等条目带位置与血缘,管线**按名查 catalog 拿位置**来跑、产物注册为派生条目。这是地基级(动 fileset 语义 + 服务边界 + 契约),且与 ADR-016/018/008 有口径交叉,故落 ADR。

## Decision
1. **一等数据集 + 血缘**:每个数据集 = `data/datasets` schema 下一个 fileset,fileset properties 增 `kind`(raw|processed)、`format`(webdataset|lance)、`derived_from`(来源数据集名,processed 必填)。保留 ADR-016 的 `owner_group/owner_user/scope/location`,且**仍"group 作属性非 namespace"**。
2. **catalog 为位置真相源 + catalog-driven 读**:管线输入 = 数据集名 → **在 data-pipeline 的 prepare handler(submit 时,有用户 bearer + can())调 metadata 取该数据集 location**(`can(dataset.read)` 把关 + 须 `kind=raw`)→ 把解析出的 location 写进 JobSpec → worker 据此读。**worker 是 detached 无 bearer,故解析必须在 submit 边界完成**(不在 worker)。
3. **新增运行时依赖 pipeline→metadata + bearer 传播**:这是**新基建**(data-pipeline 现无 HTTP 客户端、Context 不带 token)——需在 handler 捕获入站 bearer + 建 metadata 只读客户端。HTTP 运行时调用,非 import,不破 `.importlinter` 分层。
4. **显式注册 + location 服务端钉死(新增逻辑)**:注册是用户显式动作。注册端点**新增**隔离逻辑:raw 省略 location → 服务端用 `DatasetPaths(bucket, enterprise_of(ctx), group, dataset).raw_prefix` 算(eid/gid 来自 ctx);processed 校验给定 Lance URI 必须落在 `DatasetPaths(...).processed_uri` 的 caller 前缀内(eid/gid from ctx)。客户端**不能**指任意 location。(注:现状注册端点直接用 `body.location`,从不钉死——本轮新增。)
5. **信任链**:catalog 的 location **只在注册闸门写入且服务端钉死** → 管线读时可信;叠加读经 `can()`。若将来开放 location 客户端可改(外部数据集 import),此不变式即破,需重审。
6. **num_samples 管线权威**(调和 ADR-008):processed 的 `num_samples` 取**作业结果 rows_written**,用户禁填——遵 ADR-008"Layer-1 字段由管线写、用户禁填"。用户仅触发注册。
7. **血缘用数据集名引用**(v1):单 catalog/单 schema 内够用;**接受"来源删后同名重注册→血缘漂移"弱点**;v-next 转不透明 datasetId。**相对 ADR-008(lineage 列 v2)本轮提前交付最小单跳血缘**。
8. **契约直接破坏性改**(owner 拍;v1 未 GA、无外部消费者):`RegisterDataset.location` 由 required 改可选+服务端控制;`PrepareJobRequest.tar_dir`(required)弃用→新增 `source_dataset`;同 PR 改全部内部消费者(worker/runner)+ 更新 oasdiff 基线。**本条改 [ADR-018](./ADR-018-data-pipeline-job-scheduling.md) 原"加法收紧"口径为"替换"**(在此显式留痕,符合宪法"改 ADR 决策须走 ADR")。
9. **catalog/schema 显式 bootstrap**:一次性命令/脚本(provisioner-lite)建 metalake+catalog+schema,**非注册时惰性 ensure**;空企业浏览列表对 404 返空(现状会 500,本轮修)。
10. **v1 边界 / v-next**:v1 = raw(webdataset tar)→ processed(lance),显式注册,catalog-driven 读,血缘就位,processed 独立可用。v-next(显式推迟):① 二次处理 processed(需 Lance→中间格式 ingest);② 多 catalog/数据域;③ 跨组共享发现/细粒度权限(Cerbos);④ Organizations 作企业。

## Consequences
**正面**:catalog 成数据集真相源(位置/格式/血缘);管线不猜路径;血缘 DAG 起步;为数据域/Organizations 铺路。
**负面/代价(接受)**:新增 pipeline→metadata 运行时依赖 + bearer 传播基建(承重墙,列首任务/探针);两处破坏性契约(内部消费者同 PR 改);metadata 新持 OSS 凭据(§5.2 分发面扩大,纳入 env-config 单一源 + prod DoD);血缘名引用有重名漂移弱点。

## Alternatives considered
- **约定读(管线猜 OSS 路径)**:简单,但不可扩展到非约定位置、catalog 不成真相源、无血缘起点。否决。
- **注册时惰性建 catalog**:语义不纯(把建租户骨架塞进注册),迁 provisioner。否决,改显式 bootstrap。
- **raw 不进 catalog(仅 processed)**:无法 catalog-driven、无血缘起点。否决。
- **num_samples 用户填**:与 ADR-008 冲突、可能不准。否决,改管线权威。

## 修订记录
- 2026-06-23 提出并经 owner 拍板转 Accepted(含契约破坏策略、num_samples 管线权威);改 ADR-018 S2a 口径为"替换";相对 ADR-008 提前交付最小单跳血缘。作为 catalog-driven 数据集特性地基。
