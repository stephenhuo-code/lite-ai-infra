# Spec(需求):S1 Plan 7 — 数据上传后端(presigned 直传 OSS)

> 需求层(WHAT / WHY)。禁技术栈/契约 schema/实现。

## 关联出口 / Sprint
- 出口:**S1 出口⑤ 的前置**(ADR-019 计划重排:Plan 7 上传后端 → Plan 8 前端)。本 plan 交付"用户经 GUI 上传原始数据到本组 `raw/`"所需的**后端能力 + 冻结契约**;前端上传页(#11)在 Plan 8 消费本契约。
- Sprint:S1(已延长,ADR-019)。前序:Plan 5 data-pipeline-service ✅、Plan 6 BFF ✅。决策:**ADR-020(上传机制=presigned 直传,Accepted)**。

## Goal & 价值
- 让最终用户能把**原始数据**经 GUI 上传到对象存储的**本组 `raw/` 隔离路径**,供后续 data-prep 清洗。
- 价值:闭合数据域第一环(先有数据才能清洗→建作业);为前端 #11 提供冻结的上传契约;证明"presigned 直传 + 控制面 can()/审计"的隔离模型在真服务上成立。

## 范围
- **In**:① 请求上传端点(can() 过 → 签 presigned PUT / multipart 逐片 URL)· ② complete 回调端点(校验对象 → 标 ready)· ③ 列原始数据端点(can() 过滤 + 分页)· RawDataset 记录与状态机 · key 三段服务端构造 · can()+审计 · GC(清超时 pending + abort 孤儿分片 + 对账)· **契约冻结**(三端点写进 `contracts/openapi/`)。
- **Out**:前端上传 UI(Plan 8)· 下载(presigned GET,单独 ADR)· STS/前端 S3 SDK 直传(S2+)· 组内**对象级**归属(v1 同组互信,ADR-020 C-1 owner 决)。
- **推迟(vN+,带理由)**:GC 调度参数化/分布式锁(v1 单副本进程内,承 ADR-018)· 上传配额/限速(先不做,登记)。

## 用户场景 & 验收(可证伪)
- **场景 1 请求上传**:作为组成员,我要拿到一张能把数据直传到本组的"通行证"。
  - **AC-1** Given 已登录组成员 When 请求上传(声明数据集名 + 本组)Then 返回 presigned URL(单)或 `UploadId`+逐片 URL + `RawDataset.id`,且 URL 目标 key 落 `{eid}/{gid}/raw/{dataset}`;RawDataset 记录置 `pending`。
  - **AC-2** Given 已登录 When 请求上传到**非本组** Then **403**(带 reason)、**零副作用**(不建记录、不签 URL)、**审计 deny**。
  - **AC-6** Given 已登录 When 数据集名/文件名含穿越字符(`/`、`..` 等)Then **400**,不签 URL。
- **场景 2 传字节(直传)+ 完成**:
  - **AC-3** Given 持 presigned URL When 浏览器/客户端直接 PUT 字节到 OSS 后调 complete(仅传 `RawDataset.id`)Then 服务端按记录 eid/gid 再过 can() + 校验对象存在 → RawDataset 转 `ready`、**审计成功**。
  - **AC-4** Given 大文件分片 When 逐片 PUT 完成后 complete Then 分片拼装成完整对象,RawDataset `ready`。
  - **AC-7** Given complete 时 OSS 上对象不存在 When 调 complete Then **409/422**,RawDataset 不转 ready。
- **场景 3 列原始数据**:**AC-5** Given 已登录 When 列原始数据 Then 只见**本组(can() 过滤)** `ready`(及自己的 `pending`)记录;跨组不出现;支持分页。
- **边界/异常**:presigned URL **过期**(TTL≤15min)后 PUT 失败 → 客户端可重新请求 presign;complete 回调丢失 → 记录留 `pending`,由 **GC** 超时清理(+ abort 未完成 multipart 防孤儿分片);complete 伪造(传他人对象 key)→ 入参只认 `RawDataset.id`、key 从记录取,伪造无效。

## 功能需求(可测)
- **FR-001** 请求上传 MUST 先 `can("data.upload", {enterprise(来自 ctx), group})`;deny MUST **零副作用 + 审计**。
- **FR-002** OSS key MUST 由**服务端**构造:`eid/gid` **取自 `ctx`(禁读请求体)**;`dataset` 与文件名段 MUST 经 `paths.py` 正则校验(拒穿越字符)后才入 key;presigned 覆盖**完整 key**(客户端改 query 越不了权)。
- **FR-003** complete 入参 MUST **仅 `RawDataset.id`**;服务端 MUST 从该记录取 key/UploadId(禁读请求体)、**按记录 eid/gid 再过 can()**、`head_object`/`complete_multipart_upload` 校验对象存在后才标 `ready`。
- **FR-004** 列原始数据响应 MUST 经 `can()` 按企业/组过滤(禁裸暴露跨企业)+ 分页(limit/offset)。
- **FR-005** RawDataset MUST 有状态机 `pending/ready/failed`;GC MUST 清超时 `pending` + 对未完成 multipart `abort_multipart_upload` + 兼审计对账(核对 OSS 对象是否存在)。
- **FR-006** presigned URL TTL MUST ≤ 15min;MAY 签 `content-length-range` 限制对象大小。
- **FR-007** 上传相关 mutation(presign 签发、complete)MUST 审计(带 key + RawDataset.id;承 §6.1 OSS 只追加)。

## 关键实体(概念级)
- **RawDataset**:上传的原始数据记录 —— id、name、enterprise_id、group_id、OSS key(`…/raw/…`)、size、**status(pending/ready/failed)**、created_at/updated_at、upload_id(分片时)。
- **UploadGrant**(请求上传的响应,概念级):presigned URL(单)或 UploadId + 逐片 URL 列表 + RawDataset.id + TTL。

## 未决
- 无静默 TBD。契约具体 schema 字段在 writing-plans 的契约冻结任务定(形态见 design "契约要点");GC 周期/TTL 分钟数留实现期(ADR-020 §3)。
