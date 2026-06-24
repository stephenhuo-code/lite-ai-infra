# catalog-driven 数据集(一等条目 + 血缘)+ 管线从 catalog 读取 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development(推荐)或 superpowers:executing-plans 逐任务执行。步骤用 checkbox(`- [ ]`)跟踪。

**Goal:** 让数据目录(Gravitino catalog)成为数据集位置的唯一真相源——每个数据集(原始/已处理)都是带 `kind/format/derived_from` 血缘的一等 fileset;管线**按数据集名查 catalog 拿位置**来跑(不再猜路径),产物注册为派生条目;打通"下载→上传→显式注册→从对象存储跑管线→注册派生"完整本地链路。

**Architecture:** prepare **handler(submit 时,有 bearer + can())** 调 metadata 读端点按名解析 location → 写进 JobSpec → worker 用 `fetch_oss_tars` 从该 OSS 位置下载 tar → 现有 `wds_to_jsonl` → DJ → Lance。注册端点**新增**:raw 省 location→服务端 `DatasetPaths.raw_prefix` 钉死、processed 校验前缀,写 kind/format/derived_from。catalog/schema 显式 bootstrap。

**Tech Stack:** FastAPI、httpx(metadata client)、boto3(`oss_boto3_config`)、Gravitino、Data-Juicer(`.dj-venv`)、React/Vite+vitest、pytest、oasdiff。

**地基:** [ADR-023](../adr/ADR-023-catalog-driven-datasets.md)(Accepted)。spec/design:[`2026-06-23-catalog-driven-datasets/`](./2026-06-23-catalog-driven-datasets/)(已过 DoR)。
**取代:** [`2026-06-23-oss-raw-to-prepare.md`](./2026-06-23-oss-raw-to-prepare.md)(其 `fetch_oss_tars` 机制并入本计划 Task 4;"约定读"换成本计划的 catalog-driven 读)。
**分支:** 从 `s1-plan8b-frontend` 拉 `catalog-driven-datasets`(前端在该分支)。
**前置(e2e 前):** `make dj-setup`;`make deps-dev`;bootstrap(Task 2)。

> **状态:✅ 已完成并合并 main(2026-06-24)。** 7 任务全部实现 + 两阶段审查通过;全链路 live 验收通过(上传→注册→建作业→管线从 catalog 读 `s3a://` 位置跑[64 进 64 出]→注册派生产物→数据集/目录可见);独立 4 维 code review 关键项闭合。**归属随本特性一并改为 owner 模型([ADR-024](../adr/ADR-024-owner-based-dataset-ownership.md),group→Cerbos v2)**;Gravitino location 用 `s3a://`(scheme 二元性)。**已知限制/v-next**:UI 算子中文标签未映射真实 DJ 算子(勾选会崩,用默认集);数据预览/列 schema 未做。下方 checkbox 反映实时完成态。

---

## File Structure
| 文件 | 责任 | 动作 |
|---|---|---|
| `docs/superpowers/plans/2026-06-23-catalog-driven-datasets/spikes/RESULTS.md` | 探针:bearer 传播链实测 | Create |
| `scripts/bootstrap_catalog.py` + Makefile 目标 | 显式建 metalake+catalog+schema(provisioner-lite) | Create/Modify |
| `services/metadata_service/app.py` | list_ds 404→空;register location 钉死 + kind/format/derived_from;_dataset 加 kind/derived_from | Modify |
| `contracts/openapi/metadata.yaml` | RegisterDataset 加 kind/format/derived_from、location 可选;Dataset 加 kind/derived_from | Modify |
| `libs/config/__init__.py` | metadata 子集加 OSS env | Modify |
| `pipelines/data_prep/oss_fetch.py` | `fetch_oss_tars` + `build_s3` | Create |
| `pipelines/data_prep/runner.py` | run_prepare 用解析到的 OSS location → fetch → wds_to_jsonl | Modify |
| `services/data_pipeline_service/metadata_client.py` | metadata 只读 HTTP 客户端(解析 location) | Create |
| `services/data_pipeline_service/app.py` + `worker.py` + JobSpec | source_dataset;prepare 捕获 bearer→解析 location | Modify |
| `contracts/openapi/data-pipeline.yaml` | PrepareJobRequest tar_dir→source_dataset | Modify |
| `frontend/src/pages/{Datasets,CreateJob}.tsx` + `src/api/{datasets,jobs}.ts` | 注册按钮 + 源下拉 + kind/血缘显示 | Modify |
| `scripts/make_coco_smoke_tar.py` | e2e 夹具 | Create |
| 各 `tests/...` | 单测 | Create |

---

## Task 1: 探针 —— bearer 传播链(承重墙,首任务)

> 证实"prepare handler 捕获入站 bearer → 调 metadata get-dataset(can() 校验)→ 拿 location"在本地真跑通。非 TDD,记 RESULTS。

**Files:** Create `docs/superpowers/plans/2026-06-23-catalog-driven-datasets/spikes/RESULTS.md`

- [x] **Step 1: 起栈 + bootstrap + 注册一个 raw 数据集(用 alice)**

Run(逐条):
```bash
make deps-dev && sleep 40
# 用 alice 的真 token(direct grant)
TOK=$(curl -s -X POST http://localhost:8080/realms/lite-ai/protocol/openid-connect/token -d grant_type=password -d client_id=gateway -d client_secret=dev-secret -d username=alice -d password=alice -d scope=openid | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
# 起 metadata(带 OSS env,因 bootstrap 要建 OSS-fileset catalog)
env $(uv run python scripts/load_env.py metadata) OSS_ENDPOINT=http://localhost:9000 OSS_ACCESS_KEY=minio OSS_SECRET_KEY=minio123 DATA_BUCKET=lite-ai uv run uvicorn services.metadata_service.main:app --port 8002 & sleep 4
```

- [x] **Step 2: 探:带 bearer 直接 GET metadata 取数据集(模拟 pipeline→metadata)**

先 bootstrap + 注册(若 Task 2/3 未做,这里手工用 ensure + create):
```bash
# 探 metadata get-dataset 端点能否凭 bearer + can() 返回 location
curl -s -H "Authorization: Bearer $TOK" "http://localhost:8002/v1/catalogs/data/schemas/datasets/datasets/coco" -w "\nHTTP %{http_code}\n"
```
Expected:能凭 bearer 拿到数据集 JSON(含 location)或 404(若未注册)。**关键验证**:metadata 端点接受 Bearer、经 `can()`、返回 `_dataset`(含 `location`)。

- [x] **Step 3: 探:FastAPI handler 能否读到入站 Authorization 头**

```bash
uv run python -c "
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
app = FastAPI()
@app.post('/x')
def x(request: Request):
    return {'authz': request.headers.get('authorization')}
r = TestClient(app).post('/x', headers={'Authorization': 'Bearer abc'})
print('captured:', r.json())
assert r.json()['authz'] == 'Bearer abc'
print('BEARER_CAPTURE_OK')
"
```
Expected: `BEARER_CAPTURE_OK` —— 证实 prepare handler 加 `request: Request` 即可捕获 bearer 转发。

- [x] **Step 4: 写 RESULTS + 应用决策规则**

决策规则:
- 上面两步通 → 按设计实现(handler 读 `request.headers["authorization"]` → 转发 metadata client)。
- 若 metadata 端点不收 Bearer / can() 阻断意外 → **退化**:handler 用已有 `ctx`(`context_from_request`)直接调 metadata(仍 submit 边界、仍经 can()),记 RESULTS。

写 `spikes/RESULTS.md`:bearer 捕获 ✅/❌、metadata get-dataset 带 bearer 返 location ✅/❌、采用方案。Commit:
```bash
git add docs/superpowers/plans/2026-06-23-catalog-driven-datasets/spikes/RESULTS.md
git commit -m "spike(catalog): bearer 传播链实测(prepare→metadata 解析 location)"
```

---

## Task 2: catalog bootstrap + 空企业列表容错 + metadata 纳入 OSS env

**Files:** Create `scripts/bootstrap_catalog.py`;Modify `Makefile`、`services/metadata_service/app.py`、`libs/config/__init__.py`、`tests/config/test_loader.py`、`tests/services/metadata/`

- [x] **Step 1: 写失败测试 —— list_ds 404→空**

`tests/services/metadata/test_list_empty.py`(照现有 metadata 测试的假 client 模式):
```python
# 注入一个 list_filesets 抛 GravitinoError(status=404) 的假 gravitino;断言 list 返回 {"datasets": []} 非 500
from services.metadata_service.app import build_app
from services.metadata_service.gravitino import GravitinoError
from fastapi.testclient import TestClient
import os

class _G:
    def list_filesets(self, ml, c, s): raise GravitinoError("404 no schema", status=404)

def test_list_empty_on_missing_catalog(monkeypatch):
    monkeypatch.setenv("LITEAI_ALLOW_TEST_CLAIMS", "1")
    app = build_app(_G())
    r = TestClient(app).get("/v1/catalogs/data/schemas/datasets/datasets",
                            headers={"x-test-claims": '{"sub":"u-alice","groups":["/e-0001/g-0001/members"]}'})
    assert r.status_code == 200 and r.json() == {"datasets": []}
```
(x-test-claims 格式以 `services/_scaffold/auth.py` 现有解析为准,执行时对齐。)

- [x] **Step 2: 运行→失败**;`uv run pytest tests/services/metadata/test_list_empty.py -q` → FAIL(500/抛错)。

- [x] **Step 3: 改 list_ds 容错 404**

`services/metadata_service/app.py` 的 list_ds,`for name in gravitino.list_filesets(...)` 改:
```python
        try:
            names = gravitino.list_filesets(ml, catalog, schema)
        except GravitinoError as e:
            if getattr(e, "status", None) == 404:
                return {"datasets": []}
            raise
        out = []
        for name in names:
            fs = gravitino.get_fileset(ml, catalog, schema, name)
            if not _owner_group(fs):
                continue
            if can(ctx, "dataset.read", _resource(ent, fs)).allow:
                out.append(_dataset(ent, fs))
        return {"datasets": out}
```

- [x] **Step 4: bootstrap 脚本 + make 目标**

`scripts/bootstrap_catalog.py`:
```python
#!/usr/bin/env python3
"""一次性建企业目录骨架:metalake(e_XXXX)+ catalog(data, OSS-fileset)+ schema(datasets)。
provisioner-lite;S2c 并入正式 provisioner。用法:bootstrap_catalog.py e-0001"""
import os, sys
from services.metadata_service.gravitino import GravitinoClient

def main(eid: str) -> int:
    ml = eid.replace("-", "_")
    g = GravitinoClient(base_url=os.environ.get("GRAVITINO_URL", "http://localhost:8091"))
    g.ensure_metalake(ml)
    g.ensure_catalog(ml, "data", bucket=os.environ["DATA_BUCKET"],
                     s3_endpoint=os.environ["OSS_ENDPOINT"],
                     access_key=os.environ["OSS_ACCESS_KEY"], secret_key=os.environ["OSS_SECRET_KEY"])
    g.ensure_schema(ml, "data", "datasets")
    print(f"bootstrapped {ml}/data/datasets")
    return 0

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "e-0001"))
```
`Makefile` 加:
```makefile
bootstrap-catalog: ; env $$($(LOAD) metadata) OSS_ENDPOINT=http://localhost:9000 OSS_ACCESS_KEY=minio OSS_SECRET_KEY=minio123 DATA_BUCKET=lite-ai uv run python scripts/bootstrap_catalog.py $(EID)
```
(`EID ?= e-0001`;加进 `.PHONY`。)

- [x] **Step 5: metadata 纳入 OSS env(单一源)**

`libs/config/__init__.py:SERVICE_ENV_KEYS["metadata"]` 加 `OSS_ENDPOINT, OSS_ACCESS_KEY, OSS_SECRET_KEY, DATA_BUCKET`(值已在 configs/local.yaml)。更新 `tests/config/test_loader.py` 的 metadata 基线键集断言(原 `{LITEAI_JWKS_URL, GRAVITINO_URL}` → 加这 4 个)。

- [x] **Step 6: 运行 + Commit**

`uv run pytest tests/services/metadata/test_list_empty.py tests/config/ -q` → PASS。
```bash
git add services/metadata_service/app.py scripts/bootstrap_catalog.py Makefile libs/config/__init__.py tests/services/metadata/test_list_empty.py tests/config/test_loader.py
git commit -m "feat(metadata): 空企业 list 404→空 + catalog bootstrap 脚本 + metadata 纳入 OSS env"
```

---

## Task 3: 注册 location 服务端钉死 + kind/format/derived_from(+ 隔离负例)

**Files:** Modify `contracts/openapi/metadata.yaml`、`services/metadata_service/app.py`;Test `tests/services/metadata/test_register_pin.py`

- [x] **Step 1: 改契约**

`contracts/openapi/metadata.yaml`:
- `RegisterDataset`:`required` 去掉 `location`;加 `kind: {type: string, enum: [raw, processed]}`(必,加进 required)、`format: {type: [string,'null']}`、`derived_from: {type: [string,'null']}`。
- `Dataset`(读模型):加 `kind: {type: [string,'null']}`、`derived_from: {type: [string,'null']}`。
- `make gen` 重生成。

- [x] **Step 2: 写失败测试(raw 钉死 + processed 前缀校验 + kind 写入 + 隔离负例)**

`tests/services/metadata/test_register_pin.py`:
```python
# 用假 gravitino 捕获 create_fileset 的 location/properties
from services.metadata_service.app import build_app
from fastapi.testclient import TestClient

class _G:
    def __init__(self): self.last=None
    def create_fileset(self, ml, c, s, name, location, comment="", properties=None):
        self.last={"location":location,"props":properties,"name":name}
        return {"name":name,"storageLocation":location,"properties":properties,"audit":{}}

def _hdr(): return {"x-test-claims": '{"sub":"u-alice","groups":["/e-0001/g-0001/members"]}'}

def test_raw_register_pins_location(monkeypatch):
    monkeypatch.setenv("LITEAI_ALLOW_TEST_CLAIMS","1"); monkeypatch.setenv("DATA_BUCKET","lite-ai")
    g=_G(); c=TestClient(build_app(g))
    r=c.post("/v1/catalogs/data/schemas/datasets/datasets",
             json={"name":"coco","group_id":"g-0001","kind":"raw"}, headers=_hdr())  # 无 location
    assert r.status_code==201
    assert g.last["location"]=="s3://lite-ai/e-0001/g-0001/raw/coco/"   # 服务端钉死
    assert g.last["props"]["kind"]=="raw" and g.last["props"]["format"]=="webdataset"

def test_processed_register_rejects_foreign_location(monkeypatch):
    monkeypatch.setenv("LITEAI_ALLOW_TEST_CLAIMS","1"); monkeypatch.setenv("DATA_BUCKET","lite-ai")
    g=_G(); c=TestClient(build_app(g))
    r=c.post("/v1/catalogs/data/schemas/datasets/datasets",
             json={"name":"x","group_id":"g-0001","kind":"processed","format":"lance",
                   "derived_from":"coco","location":"s3://lite-ai/e-0001/g-0002/processed/x.lance"},  # 别组!
             headers=_hdr())
    assert r.status_code==403   # 越权位置被拒
```

- [x] **Step 3: 运行→失败**;`uv run pytest tests/services/metadata/test_register_pin.py -q` → FAIL。

- [x] **Step 4: 改 register 端点**

`services/metadata_service/app.py` register,在 can() 通过后、建 props 处改为:
```python
        from pipelines.data_prep.paths import DatasetPaths  # services→pipelines 允许(.importlinter)
        paths = DatasetPaths(bucket=os.environ["DATA_BUCKET"], enterprise_id=EnterpriseId(ent),
                             group_id=GroupId(body.group_id), dataset=body.name)
        kind = body.kind
        if kind == "raw":
            location = paths.raw_prefix and f"s3://{os.environ['DATA_BUCKET']}/{paths.raw_prefix}"
            fmt = "webdataset"
        else:  # processed
            location = body.location or ""
            if not location.startswith(f"s3://{os.environ['DATA_BUCKET']}/{paths._base}/processed/"):
                return JSONResponse(status_code=403, content={"reason": "location outside caller prefix"})
            fmt = body.format or "lance"
        props = {"owner_group": body.group_id, "owner_user": ctx.user, "scope": scope, "kind": kind, "format": fmt}
        if body.derived_from: props["derived_from"] = body.derived_from
        if body.num_samples is not None: props["num_samples"] = str(body.num_samples)
        if body.size_bytes is not None: props["size_bytes"] = str(body.size_bytes)
        # create_fileset(... location ...) 不变
```
(顶部 `import os`;`paths._base` = `{eid}/{gid}`。注:raw 的 location 用 `raw_prefix`(`{eid}/{gid}/raw/{name}/`)拼成 `s3://bucket/<prefix>`。)
`_dataset` 加输出:`"kind": p.get("kind"), "derived_from": p.get("derived_from")`(`kind=None` → 前端显未知,不臆断)。

- [x] **Step 5: 运行 + Commit**

`uv run pytest tests/services/metadata/ -q && make gen && uv run lint-imports` → PASS/KEPT。
```bash
git add contracts/openapi/metadata.yaml libs/contracts_gen/metadata_models.py services/metadata_service/app.py tests/services/metadata/test_register_pin.py
git commit -m "feat(metadata): 注册 location 服务端钉死 + kind/format/derived_from(隔离负例)"
```

---

## Task 4: `fetch_oss_tars` + run_prepare 用解析到的 OSS location

**Files:** Create `pipelines/data_prep/oss_fetch.py`、`tests/pipelines/test_oss_fetch.py`;Modify `pipelines/data_prep/runner.py`、`tests/pipelines/test_runner_oss.py`

> `fetch_oss_tars` 代码 + 测试 = 取自被取代的 `oss-raw-to-prepare.md` Task 1/2(原样并入)。

- [x] **Step 1: `fetch_oss_tars`(同 oss-raw-to-prepare Task 1 的实现 + 测试)**

Create `pipelines/data_prep/oss_fetch.py`:
```python
from __future__ import annotations
import os
from pathlib import Path
import boto3
from libs.audit.oss_audit import oss_boto3_config

def build_s3(endpoint, access_key, secret_key, session_token=None, region="cn-hangzhou"):
    return boto3.client("s3", endpoint_url=endpoint, aws_access_key_id=access_key,
                        aws_secret_access_key=secret_key, aws_session_token=session_token,
                        region_name=region, config=oss_boto3_config(endpoint))

def fetch_oss_tars(s3, *, bucket: str, prefix: str, dest_dir: str) -> int:
    dest = Path(dest_dir); dest.mkdir(parents=True, exist_ok=True); n = 0
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if not key.endswith(".tar"): continue
            s3.download_file(bucket, key, str(dest / os.path.basename(key))); n += 1
    return n
```
Test `tests/pipelines/test_oss_fetch.py`(用假 s3:list_objects_v2 paginator + download_file,断言只下该前缀 *.tar、返回数 = tar 个数)。运行 red→green。

- [x] **Step 2: run_prepare 用解析到的 OSS location**

run_prepare 现签名:`req.tar_dir` 是本地路径。改:`req` 增 `source_location`(OSS `s3://bucket/eid/gid/raw/ds/` 前缀,由服务层从 catalog 解析后传入)。run_prepare:若 `source_location` 给定 → `build_s3` + `fetch_oss_tars(prefix=去掉 s3://bucket/ 的 key 前缀, dest=work/tars)` → 用该本地目录喂 `convert_fn`。加 `fetch_fn=fetch_oss_tars` seam 便于测试。测试 `tests/pipelines/test_runner_oss.py`:注入 fake fetch,断言用 source_location 解析出的前缀、convert 收到本地 dest。(细节同被取代计划 Task 2,signature 用 `source_location` 替 `tar_dir` 缺省逻辑。)

- [x] **Step 3: 运行 + Commit**

`uv run pytest tests/pipelines/ -q` → PASS。
```bash
git add pipelines/data_prep/oss_fetch.py pipelines/data_prep/runner.py tests/pipelines/test_oss_fetch.py tests/pipelines/test_runner_oss.py
git commit -m "feat(pipeline): fetch_oss_tars + run_prepare 用 source_location 从 OSS 取(并入 oss-raw-to-prepare)"
```

---

## Task 5: data-pipeline catalog-driven —— source_dataset + metadata client 解析 location

**Files:** Create `services/data_pipeline_service/metadata_client.py`、`tests/services/data_pipeline/test_resolve.py`;Modify `contracts/openapi/data-pipeline.yaml`、`services/data_pipeline_service/app.py`、`worker.py`、JobSpec、`tests/services/data_pipeline/`

- [x] **Step 1: metadata 只读客户端**

`services/data_pipeline_service/metadata_client.py`:
```python
from __future__ import annotations
import os
import httpx

class MetadataClient:
    """data-pipeline → metadata 只读:按名解析数据集 location(带用户 bearer,经 metadata can())。"""
    def __init__(self, base_url: str | None = None, transport=None):
        self._c = httpx.Client(base_url=base_url or os.environ["METADATA_URL"], timeout=15, transport=transport)

    def get_dataset(self, catalog, schema, name, *, bearer: str) -> dict:
        r = self._c.get(f"/v1/catalogs/{catalog}/schemas/{schema}/datasets/{name}",
                        headers={"Authorization": bearer} if bearer else {})
        r.raise_for_status()
        return r.json()
```
(`METADATA_URL` 需进 data-pipeline 的 `SERVICE_ENV_KEYS`——加之 + 基线测试。)

- [x] **Step 2: 改契约 tar_dir→source_dataset**

`contracts/openapi/data-pipeline.yaml` PrepareJobRequest:`required: [dataset, group_id, source_dataset]`(去 tar_dir);加 `source_dataset: {type: string, pattern: '^[a-z0-9][a-z0-9_-]{0,63}$'}`;删 `tar_dir`。`make gen`。**更新 oasdiff 基线**(本轮破坏性,owner 已拍)。

- [x] **Step 3: 写失败测试(prepare 解析 location;须 kind=raw;不存在→错)**

`tests/services/data_pipeline/test_resolve.py`:注入 fake MetadataClient(get_dataset 返 `{kind:"raw", location:"s3://lite-ai/e-0001/g-0001/raw/coco/"}`),断言 prepare 把 source_location 写进 JobSpec;再注入返回 `kind:"processed"` → prepare 拒(400 "源须为原始数据集");注入抛 404 → prepare 400 "源数据集不存在/不可读"。

- [x] **Step 4: 改 prepare handler(捕获 bearer + 解析)**

`services/data_pipeline_service/app.py` prepare:加 `request: Request`;在 can() 后:
```python
        bearer = request.headers.get("authorization", "")
        try:
            ds = metadata.get_dataset("data", "datasets", body.source_dataset, bearer=bearer)
        except Exception:
            return JSONResponse(status_code=400, content={"reason": "源数据集不存在/不可读"})
        if ds.get("kind") != "raw":
            return JSONResponse(status_code=400, content={"reason": "源须为原始数据集(v1)"})
        source_location = ds["location"]
        spec = JobSpec(..., source_location=source_location, dataset=body.dataset, ...)  # 去 tar_dir
```
(`metadata` = build_app 注入的 MetadataClient,默认 `MetadataClient()`;测试注入 fake。)`JobSpec` 加 `source_location`、去 `tar_dir`;`worker.py` 构造 `PrepareRequest(source_location=spec.source_location, ...)`(去 tar_dir)。

- [x] **Step 5: 运行 + Commit**

`uv run pytest tests/services/data_pipeline/ -q && make gen && uv run lint-imports` → PASS/KEPT。
```bash
git add services/data_pipeline_service/ contracts/openapi/data-pipeline.yaml libs/contracts_gen/data_pipeline_models.py libs/config/__init__.py tests/services/data_pipeline/test_resolve.py tests/config/test_loader.py
git commit -m "feat(data-pipeline): catalog-driven —— source_dataset + metadata client 解析 location(submit 时,bearer+can())"
```

---

## Task 6: 前端 —— 注册按钮 + 源下拉 + kind/血缘显示

**Files:** Modify `frontend/src/pages/{Datasets,CreateJob}.tsx`、`frontend/src/api/{datasets,jobs}.ts`;Test 对应 `.test.tsx`

- [x] **Step 1: datasets API:注册 + 列表带 kind/血缘**

`frontend/src/api/datasets.ts`:`registerDataset(body)` = `api.post('/v1/catalogs/data/schemas/datasets/datasets', body)`;类型从生成的 metadata 类型取(含 kind/derived_from)。

- [x] **Step 2: Datasets 页:原始数据「注册」按钮 + 显示 kind/格式**

原始上传(`/v1/data/raw` 的 ready 项)行加「注册到目录」按钮 → `registerDataset({name, group_id, kind:"raw"})`(无 location);注册成功刷新。列显示 kind(原始/已处理)、format;已处理显示 `derived_from`(来源)。测试:点注册 → POST body 含 `kind:"raw"` 无 location。

- [x] **Step 3: CreateJob 源下拉(catalog 里 kind=raw 的数据集)**

源改 `<select>`:`api.get('/v1/catalogs/data/schemas/datasets/datasets')` → 过滤 `kind==='raw'` → option;提交 `createJob({dataset(产出名), group_id, source_dataset:选中名, np?, process?})`(去 tar_dir)。测试:下拉只列 kind=raw;提交 body 含 source_dataset、无 tar_dir。

- [x] **Step 4: 作业成功「注册产物」(num_samples 取自 job,只读)**

Pipelines 页作业详情:succeeded 作业加「注册产物」→ `registerDataset({name(产出名), group_id, kind:"processed", format:"lance", location:job.lance_uri, derived_from:source, num_samples:job.rows_written})`。num_samples 字段**只读自 job**(用户不可编辑,FR-010)。二次处理已处理数据集的入口显「暂未提供(v-next)」(US3-AC3)。

- [x] **Step 5: 运行前端测试 + 构建 + Commit**

`cd frontend && npx vitest run && npm run build` → PASS。
```bash
git add frontend/src/
git commit -m "feat(frontend): 注册按钮(raw/processed)+ CreateJob 源下拉 + kind/血缘显示"
```

---

## Task 7: e2e 夹具 + owner-readable runbook + 全绿门禁

**Files:** Create `scripts/make_coco_smoke_tar.py`;Modify 本计划(嵌 runbook)

- [x] **Step 1: coco webdataset tar 夹具**(同 oss-raw-to-prepare Task 6 的脚本:取 coco-30-val ~64 条 → `{key}.jpg`+`{key}.txt` tar)。Commit。

- [x] **Step 2: 全绿门禁**

`make gen && make lint && uv run pytest -q` 全绿;`cd frontend && npx vitest run` 绿;oasdiff 基线已更新(破坏性变更预期内)。

- [x] **Step 3: runbook 写入本文件 + Commit**

---

## 手动验收 Runbook(owner 逐步跑,白话)

> 仓库根目录、终端逐条。前置:Docker 在跑;已 `make dj-setup`。

- [x] **1. 起栈 + 建目录骨架**
  - 跑:`make up`(等 ~40 秒)
  - 跑:`make bootstrap-catalog`
  - 应看到:`bootstrapped e_0001/data/datasets`。
- [x] **2. 造夹具 tar(本地)**
  - 跑:`uv run --with datasets --with pillow python scripts/make_coco_smoke_tar.py`(产出 `./.smoke/coco-smoke.tar`;`datasets`/`pillow` 是夹具专用依赖,`--with` 临时带,不进项目 deps)
  - **国内网络连不上 HuggingFace** 时,前面加镜像:`HF_ENDPOINT=https://hf-mirror.com uv run --with datasets --with pillow python scripts/make_coco_smoke_tar.py`
  - 应看到:`./.smoke/coco-smoke.tar` 生成。
  - 注:**不再手工 `mc cp` 到固定路径**——owner 模型下数据落点 `e-0001/{你的用户}/raw/...` 由服务端按你的身份钉死,手工拷到 `g-0001` 路径反而对不上。改走下一步**网页上传**(这也是本轮修 422 的验证点)。
- [x] **3. 浏览器:上传原始数据集(验 422 已修)**
  - `http://localhost:8090` 登录(alice/alice)→ 数据集页 →「上传数据集」→ 数据集名 `coco`、选 `./.smoke/coco-smoke.tar` → 上传。
  - 应看到:**上传成功(不再 422)**,进度走完;数据落到 `e-0001/{你的用户 sub}/raw/coco/`(服务端钉死,你无需也无法指定路径)。
- [x] **4. 浏览器:注册原始数据集**
  - 对刚上传的 `coco` 点「注册到目录」(不需要填组)。
  - 应看到:`coco` 作为**原始**数据集出现在数据目录,**归属显示 owner=你(创建人)**、带格式;重复注册被拒。
- [x] **5. 创建作业(从目录选源,不填路径/不选组)**
  - 「创建作业」→ 源下拉选 **coco** → 产出名填 `coco-clean` → 提交(**已无「组」字段**)。
  - 应看到:作业提交,跳数据管线页。
- [x] **6. 等作业成功**
  - 数据管线页那条作业 处理中 → **成功**(几十秒)= **管线真的从目录解析到 coco 的 OSS 位置、读取并清洗、写回了 Lance**。
- [x] **7. 注册产物**
  - 作业详情点「注册产物」(样本数已自动填好,不用改)。
  - 应看到:`coco-clean` 作为**已处理**数据集出现,**显示派生自 coco**、归属 owner=你。
- [x] **8. 看血缘 + 位置(可选)**
  - 数据目录里 `coco`(原始)与 `coco-clean`(已处理,来源=coco)两条都在,两条归属都显示 owner=你。

> 任何一步对不上贴输出给我。全过 = catalog-driven 全链路通(下载→上传→注册→管线从目录读→处理→注册派生)。

---

## Self-Review
- US0 bootstrap → Task 2;US1 注册 raw + location 钉死 → Task 3 + Task 6;US2 管线按名查目录 → Task 1(探针)+ Task 5 + Task 4;US3 派生注册 + 血缘 + 二次处理占位 → Task 5/6;US4 前端显示/选源 → Task 6。✅
- FR-001~010:一等条目(kind/format)Task3;血缘 derived_from Task3/5/6;显式注册+钉死 Task3;管线查目录读 Task5/4;派生注册 Task5/6;bootstrap+404空 Task2;重复拒(现有 409)+null-safe(_dataset)Task3;不破 CI(门禁)Task7;前端 Task6;num_samples 管线权威(job.rows_written 只读)Task6。✅
- SC-001~008 → runbook 步骤 + 各单测。✅
- 隔离:raw 钉死 + processed 前缀校验(负例测试 Task3)+ 管线读经 metadata can()(Task5)。✅
- 探针(承重墙):Task 1 首位,带退化规则。✅
- Placeholder 扫描:test-claims 格式/oasdiff 基线/JobSpec 字段位置标"执行时按实际对齐",非缺口。
- 类型一致:`kind/format/derived_from`(契约+_dataset+前端)、`source_dataset`(契约)→`source_location`(JobSpec/PrepareRequest)、`fetch_oss_tars`/`MetadataClient.get_dataset` 跨任务一致。✅
