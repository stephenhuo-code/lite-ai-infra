# Design(设计):S1 Plan 7 — 数据上传后端(presigned 直传 OSS)

> 设计层(HOW)。引用既有家、不复制:机制→ADR-020;探查事实→`spikes/oss_upload/probe.md`;租户→ADR-016;持久化→ADR-018(status-file Store)。

## 架构
- **挂在 data-pipeline-service**(`services/data_pipeline_service/app.py:build_app` 工厂),复用现有 `can()`(`libs/authz`)+ 审计(`libs/audit/oss_audit.py`)+ boto3 客户端 + key 规范(`pipelines/data_prep/paths.py`)。新增上传路由模块(如 `upload.py`)+ `RawDatasetStore`。
- **控制面经 BFF/gateway,数据面绕过**(ADR-020):请求上传 / complete / 列原始数据三端点经 gateway(can()/审计/CSRF);**字节由客户端直传 OSS,不过 gateway**(规避 `proxy.py:33` 全量进内存的硬伤,探查 §5)。

## 核心流程(三段式,详 ADR-020 §1)
1. **请求上传** `POST /v1/data/raw`(经 BFF):`can("data.upload",{eid(ctx),gid})` → 通过则服务端拼 key(`paths.raw_prefix` + 校验过的 dataset/文件名)→ 建 `RawDataset(pending)` → `boto3.generate_presigned_url("put_object"…)`(单)或 `create_multipart_upload` + 逐片 `generate_presigned_url("upload_part"…)`(分片)→ 返回 grant。
2. **传字节**:客户端直 PUT 到 OSS(单 / 分片;探查 §1/§2 实测通)。
3. **完成** `POST /v1/data/raw/{id}/complete`:入参仅 id → 取记录 key/upload_id → **再 can()** → `head_object`(单)/ `complete_multipart_upload`(分片,带各片 ETag)→ 校验存在 → `ready` + 审计;失败 → `failed`/留 `pending`。
- **列原始数据** `GET /v1/data/raw`:`can()` 按企业/组过滤(对齐 ADR-019 I-1 list 模式)+ 分页。

## 数据模型
- **RawDataset**:`id, name, enterprise_id, group_id, oss_key, size, status(pending|ready|failed), upload_id?, created_at, updated_at`。
  - **状态机**:`presign 签发→pending`;`complete 校验通过→ready`;`complete 失败/abort→failed`;`pending +TTL 超时→(GC) 删除`(ADR-020 §3)。
- **持久化 = status-file Store(ADR-018,v1 无 PG)**:**镜像 `services/data_pipeline_service/jobs.py:JobStore`** —— 每条 RawDataset 一目录,`spec.json` 写一次 + `status.json` 经 **temp + `os.replace` 原子替换**(跨进程读者不见半写文件)。新 `RawDatasetStore` 复刻该模式,不引入新存储基建。
- **隔离编码**:key 走 `pipelines/data_prep/paths.py` 的 `{eid}/{gid}/raw/{dataset}` 规范;`eid/gid` 来自 `ctx`。

## 授权与安全(ADR-020 C-1/C-2)
- **presign 时 can()**:`can("data.upload", {enterprise(ctx), group})` 过才签;deny 零副作用 + 审计。
- **key 三段服务端钉死**:`eid/gid` 取自 `ctx`(**禁读请求体**);`dataset`/文件名经 `paths.py` 正则(拒 `/`、`.`、`..`)→ presigned 覆盖完整 key,客户端改 query 越不了权。
- **complete 防伪**:入参仅 `RawDataset.id`,key 从记录取、**再过 can()**;`head_object` 只证存在、不作归属凭证。
- **粒度(owner 决,登记)**:can() 判到**组级**;v1 **组内同组互信**(可覆盖同组对象),vN+ 再细化对象级归属。
- **能力凭据**:presigned TTL≤15min、key 写死、可签 `content-length-range`;泄露窗口内只能写那一个 key。

## 非功能(NFR)
- **扩展性**:字节不过 gateway → 无内存硬伤;大文件 + 断点续传由分片 presign 天然支持。
- **dev/prod parity(探查 §3,parity 陷阱)**:dev MinIO 默认放行 CORS;**prod 阿里云 OSS 必须显式配 bucket CORS(允许前端域名、PUT、暴露 ETag)= prod 上线 DoD 硬门**;**prod virtual-hosted addressing + multipart ETag 行为须 staging 复验**(dev path-style PASS ≠ prod PASS);prod OSS 域名进前端 CSP `connect-src`(Plan 8)。
- **审计**:presign 签发 + complete 两点落 can()+审计;presign 审计带 key+TTL+id 使 GC 可事后对账(ADR-020 I-2)。
- **可靠性**:两段提交非原子 → GC 兜底(清超时 pending + abort 孤儿分片防漏钱)。

## 依赖与引用
- **决策(ADR)**:**ADR-020**(上传机制,Accepted)· ADR-016(租户隔离编码)· ADR-018(status-file Store 模式)· ADR-019(出口⑤/计划序)。
- **探查事实**:`spikes/oss_upload/probe.md`(presigned 单/分片实测通、CORS parity、代理内存硬伤)。
- **代码家**:`services/data_pipeline_service/{app.py,jobs.py}`(build_app + JobStore 模式)· `libs/authz`(can())· `libs/audit/oss_audit.py`(审计 + `oss_boto3_config`)· `pipelines/data_prep/paths.py`(key 规范)。
- **第一消费者(契约)**:Plan 8 前端上传页 + 原型 `prototypes/2026-06-16-data-domain-midfi.html` #11(DoR② 满足)。

## 契约要点(writing-plans 阶段冻结进 `contracts/openapi/`;承 ADR-020 I-3)
- `POST /v1/data/raw`(请求上传):入 {dataset 名, group_id, size?, multipart?};出 {raw_id, presigned_url | upload_id+part_urls, ttl}。
- `POST /v1/data/raw/{id}/complete`:入 **仅 path id**(分片附各片 ETag);出 {status}。
- `GET /v1/data/raw`:can() 过滤 + 分页;出 列表。
- **错误形态**(§5.4 带 reason):越权 403 / 名非法 400 / 对象不存在 409·422。

## 技术选型理由
- **boto3 presigned + multipart**:原生、零新依赖、探查实测通;无需重写 proxy。
- **RawDatasetStore 镜像 JobStore**:复用已验证的 v1 无 PG 原子 status-file 模式,跨进程安全,不引入新基建。

## ★ DoR 自检(进 tasks 前过门;三态:已决定 / 显式推迟+理由 / 待探查+探针+决策规则)
- [x] **1 范围与出口**:**已决定** —— 出口⑤前置;验收 AC-1~7 可证伪;in/out/推迟清;ADR-019 计划序对齐。
- [x] **2 接口契约**:**已决定(形态)** —— 三端点 req/resp/错误码形态定(上"契约要点"),writing-plans 冻结进 openapi;第一消费者=Plan 8 前端 + 原型 #11 ✓。
- [x] **3 数据模型**:**已决定** —— RawDataset 字段 + 状态机 + 隔离编码;持久化=镜像 JobStore status-file。
- [x] **4 外部依赖事实**:**已实测成文** —— `spikes/oss_upload/probe.md`(presigned 单/分片通、CORS、内存硬伤);prod virtual-hosted **留 staging 复验(显式登记,非本地可测)**。
- [x] **5 行为·边界·并发·威胁**:**已决定** —— 越权 403/零副作用、穿越名 400、complete 防伪、TTL 过期重取、孤儿分片 GC、跨进程原子写。
- [x] **6 NFR**:**已决定** —— 扩展(字节不过 gateway)/parity(prod CORS DoD 硬门 + staging 复验)/审计两点/GC 兜底。
- [x] **7 验收与测试策略**:**已决定** —— AC 可证伪 + 真 MinIO 集成(presign→直传→complete→列)+ 手动 runbook(writing-plans 出,ADR-015)+ 单元(key 校验/can()/状态机)。
- [x] **8 关键决策留痕**:**已决定** —— **ADR-020 Accepted**(C-1 同组互信、C-2 complete 防伪、I-1~4/M-1~2 全采纳)。

**结论**:8 项全过(#4 prod virtual-hosted 复验显式登记为 staging 项,非阻塞本地实现)→ **no-TBD,DoR 可过**。建议过门后进 `superpowers:writing-plans` 写 tasks(Task 1 = 契约冻结)。
