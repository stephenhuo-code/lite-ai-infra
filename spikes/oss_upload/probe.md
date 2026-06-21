# OSS 上传机制探查事实记录(Plan 7 / #11 数据集上传,宪法 §3.4 探查优先)

> 来源:对真 dev MinIO(`deploy/dev/docker-compose.yml`,`:9000`,`minio/minio123`,path-style)实测,脚本 `probe.py`。
> 日期:2026-06-20。**实现以本文件为准,禁止把猜测写进 ADR-020 / 上传契约 / tasks。**

复现:dev MinIO 起来后 `uv run python spikes/oss_upload/probe.py`(全 PASS)。

现状(由代码确认,见 Explore 报告):boto3 + S3 兼容;dev=MinIO,prod 自适配阿里云 OSS(`libs/audit/oss_audit.py:oss_boto3_config` 按域名切 path/virtual-hosted);**presigned/multipart 此前全未使用**;key 规范 `{eid}/{gid}/{raw|cleaned|processed}/{dataset}`(`pipelines/data_prep/paths.py`)。

---

## §1 presigned 单对象 PUT —— 浏览器直传可行 ✅

实测:`generate_presigned_url("put_object", …)` 出一条 URL(**长度 ~330B**),用**纯 HTTP PUT(不带任何 AWS 凭据/SDK)**上传 5 MiB → 落 `e-0001/g-0001/raw/probe/single.bin`,`head_object` size 一致。

**结论**:浏览器 `fetch(url, {method:'PUT', body:file})` 即可直传,无需把任何长期凭据下发到前端。URL 即"一次性写能力",key 在 presign 时**写死**(客户端改不了目标路径)。

## §2 presigned 分片 multipart —— 大文件直传可行 ✅

实测:`create_multipart_upload` → 对每个 part `generate_presigned_url("upload_part", PartNumber=i)` → **纯 HTTP PUT 每片** → 收集 `ETag` → `complete_multipart_upload`。3×5 MiB 分片落 `…/raw/probe/multi.bin`,size 一致。

**结论**:大文件可由前端**逐片 presign + 并行/断点续传 PUT**,服务端只发 URL 与 complete,不碰字节流。分片下限 5 MiB(末片除外,S3/MinIO 规则)。

## §3 CORS —— MinIO 默认放行;真 OSS 需显式配 ⚠ parity 缺口

实测两点:
- `put_bucket_cors`(S3 CORS API)→ **MinIO 报 ClientError(不实现该 API)**,即 **MinIO 不能用 S3 API 配 CORS**。
- 但带 `Origin: http://localhost:5173` 的 **OPTIONS 预检 → 204 且 `Access-Control-Allow-Origin: http://localhost:5173`(回显来源)**。

**结论**:**MinIO 默认对任意 Origin 放行 CORS**(回显请求 Origin),dev 浏览器直传开箱可用。**但阿里云 OSS 不默认放行**——prod 必须在 OSS 控制台/API 显式配 bucket CORS(允许前端域名、`PUT`、`ETag` 暴露头)。**这是一条 dev↔prod parity 缺口,落 ADR 缓解项 + DoD 硬门。**

## §4 STS AssumeRole —— 可达 ✅(本轮不用)

实测:MinIO STS `assume_role` 可达并返回 `Credentials`。即"下发短期受限凭据让前端自行 multipart"这条路在 MinIO 侧成立。**但比 presigned 复杂**(要建 role/policy、前端要装 S3 SDK),**本轮不采用**,记为 S2+ 放大备选。

## §5 代理流式(经 gateway/BFF 转发字节)—— 内存硬伤 ❌(由代码量化)

`services/_scaffold/proxy.py:33` 转发前 **`body = await request.body()` 全量加载进内存**(httpx client 无 `limits`/流式)。

**结论**:经 gateway 代理上传 = **整个文件进 gateway 内存**。1 GB 档单并发即 ~1 GB RAM 峰值,多并发线性叠加 → **不可扩展、易 OOM**。改造成真流式需重写 proxy(streaming request → streaming to OSS),工作量与风险都高于直接走 presigned。

---

## 决策输入汇总(供 ADR-020)

| 维度 | A. presigned 直传 OSS(单 + 分片) | B. 经 BFF/gateway 代理流式 |
|---|---|---|
| 可行性 | ✅ 实测通(§1/§2) | 需重写 proxy 为流式(现状非流式) |
| 扩展性 / 内存 | ✅ 字节不过 gateway | ❌ 全量进 gateway 内存(§5) |
| 大文件/断点续传 | ✅ 分片 presign 天然支持 | 需自建分片协议 |
| 前端是否持长期凭据 | 否(URL=一次性写能力,key 写死) | 否 |
| 同源原则 | ⚠ 字节直打 OSS,**破** FR-001 同源(仅数据面;控制面 presign/complete 仍经 gateway) | ✅ 全程同源 |
| can() + 审计落点 | **presign 签发时**(服务端 can() 过才发 URL)+ **complete 回调时**(head_object 校验 + 审计) | 转发时(字节在手) |
| CORS 依赖 | dev MinIO 默认放行;**prod OSS 必须显式配**(§3 parity 缺口) | 无(同源) |
| 隔离不变式 | URL 把 key 钉死在本组 `e-/g-/raw/`,客户端改不了 → 隔离成立 | 服务端校验 path |

**实测把先前"S1 倾向代理"的预设推翻**:代理的内存硬伤(§5)在 1 GB 档就站不住,而 presigned 直传当下即通、天然可扩展。→ **倾向 A(presigned 直传)**,代价是引入"数据面非同源 + prod OSS 需配 CORS",用"控制面经 gateway can()+审计、key 写死、短 TTL、complete 回调校验"缓解。最终由 ADR-020 拍板。
