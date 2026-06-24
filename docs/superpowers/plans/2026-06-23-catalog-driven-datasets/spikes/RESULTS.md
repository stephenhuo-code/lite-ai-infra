# Spike RESULTS — catalog-driven datasets 承重墙(bearer 传播链)

- 日期: 2026-06-23
- 分支: catalog-driven-datasets
- 地基: ADR-023 (Accepted)
- 性质: 探针(spike),非 TDD。只跑验证 / 读码,**未写生产代码**。

## 承重墙(被验证的链路)

> data-pipeline 的 prepare handler 捕获入站用户 bearer → 转发给 metadata 的 get-dataset 端点(经 `can()` 校验)→ 拿到数据集的 `location`,在 **submit 时的 handler** 解析完毕写进 JobSpec 交 worker。

为什么需要新基建(三处现状,本探针均已复核):
- data-pipeline 现**无 HTTP 客户端**(`services/data_pipeline_service/` 无 metadata client;`app.py` 仅依赖 runner/audit/uploader)。
- `libs/identity/context.py:Context`(L19–23)只有 `user / memberships / is_platform_admin`,**不带原始 token** —— 故必须在 handler 层从 HTTP 头捕获 bearer。
- worker 是 detached 子进程**无 bearer** —— 故 location 必须在 submit handler(有 bearer + can() 的边界)解析,写进 JobSpec。

---

## A. FastAPI handler 能否捕获入站 Authorization 头 — ✅

纯单测(无需栈):handler 加 `request: Request` 形参即可读到 `request.headers.get("authorization")`。

证据:运行内联单测输出 `A_BEARER_CAPTURE_OK`(`TestClient.post('/x', headers={'Authorization': 'Bearer abc'})` → handler 读回 `'Bearer abc'`,断言通过)。

结论:在 `services/data_pipeline_service/app.py` 的 `prepare`(现签名 `def prepare(body, ctx=Depends(context_from_request))`,L29)**追加 `request: Request` 形参**即可拿到原始 bearer。`context_from_request` 自身也是 `request: Request` 入参(`services/_scaffold/auth.py:23`),二者并存无冲突(同一 Request 注入)。

## B. metadata 的 get-dataset 端点凭 Bearer + can() 返回含 location 的数据集 — ✅

读码证据:
- 端点 `GET /v1/catalogs/{catalog}/schemas/{schema}/datasets/{name}` → `get_ds`,`services/metadata_service/app.py:83-96`。
- 身份: `ctx: Context = Depends(context_from_request)`(`app.py:84`)→ `services/_scaffold/auth.py:23-43`:取 `Authorization: Bearer`(L34-36),`verify_and_decode(... LITEAI_JWKS_URL ...)` 验签(L37-40),失败 401(L42)。即 **bearer 是该端点唯一生产身份来源**(test-claims seam 默认 default-deny,需 `LITEAI_ALLOW_TEST_CLAIMS=1`)。
- 授权: `can(ctx, "dataset.read", _resource(ent, fs))`(`app.py:93`);deny → 403(L94-95)。另有 fail-closed:`_owner_group` 缺失(不可归属 fileset)→ 403(L91-92)。
- location: 成功返回 `_dataset(ent, fs)`(L96),`_dataset` 把 `fs["storageLocation"]` 映射为 `location` 字段(`app.py:52`)。

活体只读探(未启动新实例,复用 owner :8002):
- `curl GET .../datasets/foo`(无 Authorization)→ **HTTP 401**。证实 `context_from_request` 鉴权门在该端点生效,bearer 缺失即拒。
- 未做"带有效 token"的活体:owner 栈无现成 token/已注册 dataset,按约束以读码结论为准(链路已逐行确认)。

结论:bearer → `context_from_request`(验签出身份)→ `can(dataset.read)` → 返回含 `location` 的 dataset。链路通。

## C. metadata 只读客户端形态可行 + METADATA_URL 是否在 data-pipeline env — ✅(客户端可行)/ 需补(env)

客户端模式 — ✅ 可行:
- metadata 自身的 `GravitinoClient`(`services/metadata_service/gravitino.py:19-47`)即 **同步 httpx**(`httpx.Client(base_url=..., timeout=15)`,`_get/_post` 同步)。data-pipeline 新建只读 metadata client 照此同步 httpx 模式即可,且需把入站 bearer 作 `Authorization` 头转发(转调 `get_ds`)。
- 注:`transport` 可注入(`httpx.BaseTransport | None`),便于单测用 `MockTransport`,无需起栈。

METADATA_URL 在 data-pipeline env — 需补:
- 单一配置源 `libs/config/__init__.py`:`_flat()` **已有 `METADATA_URL`**(L154,值 = `services.metadata_url`,local.yaml = `http://localhost:8002`)。
- 但 `SERVICE_ENV_KEYS["data-pipeline"]`(L176-177)**不含 `METADATA_URL`**(仅 JWKS/JOBS_DIR/OSS_*/DJ_BIN)。`METADATA_URL` 目前只注入给 `gateway`(L178-180)。
- **结论:需把 `"METADATA_URL"` 加入 `SERVICE_ENV_KEYS["data-pipeline"]`。** 无需改 `_flat()` / configs/*.yaml(值已存在)。

---

## 决策 / 采用方案

**采用「直采」方案**(A + B 均通):
- 在 `prepare` handler 追加 `request: Request`,读 `request.headers["authorization"]` 拿到入站用户 bearer。
- data-pipeline 新建同步 httpx 只读 metadata client(仿 `gravitino.py`),把该 bearer 作 `Authorization` 头转发到 `GET .../datasets/{name}`,由 metadata 经 `context_from_request` + `can(dataset.read)` 返回含 `location` 的 dataset。
- **location 解析在 submit handler 内完成**(此处同时有 bearer 与 can() 边界),写进 `JobSpec` 交 detached worker(worker 无 bearer,不可延后解析)。
- 退化方案(handler 用已有 `ctx` 在服务层调 metadata 内部读)**无需启用**:B 未发现 get_ds 拒 Bearer / 授权链坑。

## 配置变更需求(交付 Task 5)

- **需补**:`libs/config/__init__.py` 的 `SERVICE_ENV_KEYS["data-pipeline"]` 增加 `"METADATA_URL"`。
- 无需改 `_flat()`(已有 `METADATA_URL`)与 `configs/local.yaml`(`metadata_url: http://localhost:8002` 已在)。

## 安全 / 边界确认

- **未启动新 metadata 实例**:8002 为 owner 运行中的栈;只做无副作用 `curl GET`(返回 401)。
- **未动 owner 运行栈**:无 `make up`/`make deps-dev`/重启;无 docker 操作。
- 仅做:1 个内联 FastAPI 单测、读码、1 次只读 curl。
