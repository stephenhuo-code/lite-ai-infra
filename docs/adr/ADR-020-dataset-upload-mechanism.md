# ADR-020: 数据集上传机制 —— presigned 直传 OSS(控制面经 BFF)

- 状态：**Accepted（2026-06-21,owner 拍板）**
- 决策人：owner
- 相关：ADR-016(Gravitino 租户:enterprise=metalake、group 隔离)、ADR-019(出口⑤=真 GUI + BFF、gateway serve dist 同源、前端不持 token);constitution §1(企业/组隔离不变式)/§2.4(can() + 审计)/§3.0.2(契约先行)/§3.4(探查优先)/§4(v1 容忍);Plan 7 spec/design(`docs/superpowers/plans/2026-06-20-s1-plan7-frontend/`);**探查事实 `spikes/oss_upload/probe.md`(2026-06-20,全 PASS)**

---

## Context

原型 #11"数据集上传"要把**原始数据上传到对象存储的本组 `raw/` 路径**,供后续 data-prep 清洗。这是 Plan 7 纳入 #11 后冒出的**新后端能力**(此前服务只读/提交作业,上传字节是全新数据面),且是**地基级、影响安全与扩展性**的取舍 → 必须落 ADR(constitution §3.4 + ADR-019 先例)。

两条候选路线:
- **A. presigned 直传 OSS**:BFF/服务端按 `can()` 签发 presigned PUT(大文件用 multipart 逐片 presign),浏览器**直接 PUT 到 OSS**,字节不过 gateway。
- **B. 经 BFF/gateway 代理流式**:浏览器→gateway→OSS,字节穿服务端。

**探查已推翻先前"S1 倾向代理"的预设**(`spikes/oss_upload/probe.md`,对真 dev MinIO 实测):
- §1/§2:presigned 单传 + 分片直传**当下即通**(纯 HTTP PUT、前端不持任何长期凭据、key 在 presign 时写死)。
- §5:**代理路线有内存硬伤**——`services/_scaffold/proxy.py:33` 转发前 `await request.body()` **全量进 gateway 内存**(httpx 非流式)。1 GB 档单并发即 ~1 GB RAM 峰值,多并发线性叠加,易 OOM;改真流式需重写 proxy,风险/工作量都高。
- §3:**MinIO 默认放行 CORS(回显 Origin)**,dev 开箱可用;但**阿里云 OSS 不默认放行**,prod 须显式配 bucket CORS(parity 缺口)。
- §4:STS AssumeRole 在 MinIO 可达,但比 presigned 复杂(建 role/policy + 前端装 S3 SDK),本轮不取。

## Decision

**采用 A:presigned 直传 OSS;控制面(授权/审计/登记)经 BFF,数据面(字节)浏览器直打 OSS。**

1. **三段式流程(控制面经 gateway,数据面绕过)**:
   1. **请求上传**:前端 → BFF/data-pipeline-service `POST`(声明数据集名 + 目标组)→ 服务端 **`can("data.upload", {enterprise,group})`** 过闸(deny 零副作用 + 审计)→ 通过则**服务端拼 key**(`{eid}/{gid}/raw/{dataset}` 经 `pipelines/data_prep/paths.py` 规范)、建 **RawDataset(pending)** 记录、返回 **presigned URL(单)或 UploadId + 逐片 presigned URL(分片)**。
   2. **传字节**:浏览器**直接 PUT 到 OSS**(单 PUT 或并行/续传分片 PUT);字节不过 gateway。
   3. **完成回调**:前端 → BFF/服务端 `POST .../complete`,**入参仅 `RawDataset.id`**(服务端 pending 记录主键)→ 服务端从该记录取 key/UploadId(**绝不从请求体取**)、**按记录的 eid/gid 再过一次 `can()`** → `head_object`/`complete_multipart_upload` **校验对象存在**、标 RawDataset(ready)、**审计成功**。`head_object` 只证"对象存在",**不作归属凭证**(C-2)。回调缺失/校验失败 → RawDataset 转 `failed` 或留 `pending` 待 GC。

2. **隔离不变式靠"key 三段服务端钉死 + presign 时 can()"双保**(C-1):
   - **`eid/gid` 必来自 `ctx`**(会话解析的企业/组),**绝不读请求体**;`dataset` 段与文件名段**必经 `pipelines/data_prep/paths.py` 正则校验**(拒 `/`、`.`、`..` 等穿越字符)后才拼进 key。presigned URL 把**完整 key**钉死(签名覆盖整串 key),客户端改 query 也越不了权 → 满足 constitution §1.6 隔离不变式 + §2.4 `can()` 唯一出入口。
   - **粒度登记(owner 风险接受)**:`can("data.upload", {enterprise,group})` 只判到**组级**;v1 **不做组内 dataset/对象级归属**(同组互信,组内成员可覆盖同组对象)。显式登记,vN+ 再细化对象级归属。**——"key 写死"守的是跨组隔离,不等于对象级隔离。**

3. **状态机(ADR 定骨架,参数留实现期)**:RawDataset 状态集 **`pending / ready / failed`**。转移:presign 签发→`pending`;complete 校验通过→`ready`;complete 校验失败 / abort→`failed`。**GC**:按 `pending` 创建时间 + TTL 超时扫描,清记录 **且对 multipart 未完成上传 `abort_multipart_upload`**(防 OSS 留计费孤儿分片漏钱)+ **兼任审计对账兜底**(核对 OSS 对象是否存在,使"授权了但结果未知"的中间态可事后对账)。GC 周期/TTL 分钟数留实现期。

4. **能力凭据风险(登记,owner 接受)**:presigned URL = 一次性写能力,**短 TTL ≤ 15min**;泄露窗口内只能写**那一个 key**(写死),不能列/读/越权;prod 走 HTTPS。presign **可签 `content-length-range` 限制对象大小**(防 TTL 窗口内写超额对象的配额滥用面,M-2)。比"下发长期凭据到前端"安全得多。

5. **同源原则的显式豁免 + 形式化判据(修订 Plan 7 design FR-001;I-1)**:
   - **判据**:**凡携带 BFF 会话 cookie / 触发服务端 `can()` 决策的请求,一律同源经 gateway;仅凭 presigned 一次性能力、不带 cookie、不触发服务端授权决策的纯字节传输,才允许非同源。** presigned PUT 不带 cookie、不是 OIDC token,故与 ADR-019"前端不持 token / 同源 serving"**不冲突**(那两条初衷=保护会话 cookie,在数据面本不适用)。
   - **范围只限上传**:本 ADR **只覆盖上传**(presigned PUT/multipart)。**下载(presigned GET)的读越权面不同,单独立 ADR**,不在此豁免内。

6. **CORS = prod DoD 硬门(parity 缺口,探查 §3)**:dev MinIO 默认放行无需配;**prod 阿里云 OSS 必须显式配 bucket CORS**(允许前端域名 Origin、`PUT`、暴露 `ETag` 头)。列入上传后端 plan 的 prod 上线 DoD,**不得静默遗漏**(否则 prod 上传必跨域失败)。**prod virtual-hosted addressing 下 presign 直传 + multipart ETag 行为须在 staging 复验**(dev path-style PASS ≠ prod PASS,M-1);prod OSS 域名须进前端 **CSP `connect-src`**。

7. **分片阈值**:小文件单 PUT;超阈值(建议 ≥ 64–128 MiB,实现期定)走 multipart,分片 ≥ 5 MiB(末片除外,S3/MinIO 规则,探查 §2)。S1 目标档 ~1 GB。

8. **STS / 直传 SDK 推迟**:§探查 §4 可达但复杂,记为 **S2+ 放大备选**(超大文件 / 更细粒度凭据时再上)。

## 独立 plan 必须冻结的契约要点(指针,非定死字段;I-3)

上传后端拆为 Plan 7 前置的**独立 plan**(owner 决)。该 plan 进 tasks 前,以下**必须在契约(`contracts/openapi/`)里冻结**(契约先行,constitution §3.0.2 + §4.2):
- **三端点 req/resp**:① 请求上传(入参:dataset 名、目标组、文件大小/是否分片;出参:presigned URL 或 `UploadId`+逐片 URL + `RawDataset.id`)② **complete**(入参 **仅 `RawDataset.id`**,见 C-2)③ **列原始数据**(`GET`,响应**经 `can()` 按企业/组过滤** + 分页,对齐 ADR-019 I-1 的 list 模式)。
- **错误形态/状态码**(constitution §5.4 带 reason):越权→**403**;dataset/文件名非法→**400**;TTL 过期 PUT 失败 → 前端**重新请求 presign** 的契约;complete 时对象不存在→**409/422**。
- **状态机**:RawDataset `pending → ready` / `pending →(complete 失败/abort)→ failed` / `pending →(GC 超时)→ 删除`。

## Consequences

**正面**:
- **可扩展**:字节不过 gateway,无 §5 内存硬伤;大文件 + 断点续传天然支持(分片 presign)。
- **安全**:前端不持长期凭据;key 写死 + presign 时 can() → 隔离不变式成立;短 TTL。
- **复用现状**:boto3 已在;presigned/multipart 是 boto3 原生,无新依赖、无需重写 proxy。
- **控制面仍有 can()+审计**:授权与审计在 presign 签发 + complete 回调两点落,审计链完整。

**负面 / 已知**:
- **数据面非同源**(豁免 FR-001):前端需知道 OSS endpoint(presigned URL 自带),拓扑比"全程同源"复杂一点。
- **prod 必须配 OSS CORS**(DoD 硬门),否则 prod 上传跨域失败——dev 测不出(MinIO 默认放行),是 parity 陷阱。
- **两段提交**(presign + complete):complete 回调丢失会留 pending RawDataset,需 GC;非原子。
- **presigned URL 是 bearer 能力**:泄露窗口内可写该 key(已用短 TTL + key 写死 + 可选 content-length-range 缓解,登记接受)。
- **审计中间态(I-2,v1 事后尽力容忍)**:"字节已落 OSS 但 complete 丢失"这笔操作只有 presign 签发审计、无落地审计。缓解:**presign 审计须带 key + TTL + `RawDataset.id`**,使 GC 扫 pending 超时时能核对 OSS 对象是否存在 → "授权了但结果未知"的中间态可事后对账(GC 兼审计兜底,见 Decision §3)。

## Alternatives considered

- **B. 经 BFF/gateway 代理流式** —— **否决**:proxy 现状非流式(全量进内存,§5),1 GB 档即 OOM 风险;改真流式重写成本/风险高于直接 presigned。其唯一优势(全程同源、字节在手便于校验)不抵内存硬伤。
- **C. STS AssumeRole 下发短期凭据 + 前端 S3 SDK 直传** —— 否决(本轮):探查 §4 可达但需建 role/policy + 前端装 SDK,复杂度高;留 S2+。
- **D. 服务端从宿主机路径拉(现状 `tar_dir`)** —— 否决:那是开发者本地路径,非"用户经 GUI 上传",不满足 #11。

## 修订记录

- **2026-06-20(product-architect 隔离复审采纳,仿 ADR-019 体例)**:
  - **C-1** key 三段服务端钉死(eid/gid 来自 ctx、dataset/文件名经 paths.py 正则)+ 组内对象级隔离粒度显式登记(同组互信,vN+ 细化)→ 入 Decision §2。
  - **C-2** complete 回调入参仅 `RawDataset.id`、按记录 eid/gid 再过 can()、head_object 不作归属凭证 → 入 Decision §1.3。
  - **I-1** 同源豁免形式化判据(带 cookie/触发 can() → 同源;纯字节能力 → 可非同源)+ 下载移出本 ADR 单独立 → 入 Decision §5。
  - **I-2** presign 审计带 key+TTL+id、GC 兼审计对账兜底 → 入 Consequences。
  - **I-3** 新增"独立 plan 必须冻结的契约要点"节(三端点 req/resp、错误码、状态机)。
  - **I-4** 状态机骨架 `pending/ready/failed` + GC `abort_multipart_upload` 清孤儿分片 → 入 Decision §3。
  - **M-1** prod virtual-hosted/ETag staging 复验 + CSP connect-src;**M-2** presign content-length-range → 入 Decision §4/§6。
  - 复审结论"需改后用",上述修订后交 owner 拍板转 Accepted。
