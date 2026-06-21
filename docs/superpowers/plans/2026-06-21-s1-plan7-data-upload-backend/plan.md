# 数据上传后端(presigned 直传 OSS)Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 data-pipeline-service 加"数据集上传"后端 —— presigned 直传 OSS(请求上传/完成/列原始数据三端点 + RawDataset 状态机 + can()+审计 + GC),冻结契约供 Plan 8 前端消费。

**Architecture:** 控制面经 BFF/gateway(can()/审计),数据面字节由客户端直 PUT 到 OSS(绕过 gateway 内存硬伤,ADR-020)。三段式:① `POST /v1/data/raw` can() 过 → 服务端拼 key(隔离写死)→ 建 RawDataset(pending)→ 签 presigned URL;② 客户端直传 OSS;③ `POST /v1/data/raw/{id}/complete` 仅凭 id → 再 can() → 校验对象 → ready。持久化镜像现有 `JobStore` 的 status-file 模式(v1 无 PG)。

**Tech Stack:** Python 3.12 · FastAPI · boto3(presigned/multipart,原生)· pydantic(datamodel-codegen 生成)· pytest(单元 + `@pytest.mark.integration` 真 MinIO)。

**地基与依据:** ADR-020(上传机制,Accepted)· ADR-018(status-file Store)· ADR-016(租户隔离编码)· 探查 `spikes/oss_upload/probe.md`(presigned 单/分片实测通)· spec/design 同目录。

---

## File Structure(决策锁定)

**新建:**
- `services/data_pipeline_service/raw_store.py` — `RawSpec` + `RawDatasetStore`(镜像 `jobs.py:JobStore`,status-file 原子写)。
- `services/data_pipeline_service/upload.py` — `Uploader`(presign 单/分片、create_grant、finalize、list_raw、gc;持 raw_store + s3 + data_bucket;基础设施无感,仿 `runner` 注入 `build_app`)。
- `tests/services/data_pipeline/test_raw_store.py` — RawDatasetStore 单元测试。
- `tests/services/data_pipeline/test_upload.py` — Uploader + 端点单元测试(fake s3 + MemSink + TestClient)。
- `tests/integration/test_raw_upload_e2e.py` — 真 MinIO:presign→httpx PUT→complete→list(`@pytest.mark.integration`)。

**修改:**
- `contracts/openapi/data-pipeline.yaml` — 加三端点 + schemas(契约先行)。
- `libs/contracts_gen/data_pipeline_models.py` — `make gen` 重生成(勿手改)。
- `pipelines/data_prep/paths.py:26` — 加 `raw_object_key(filename)`(文件名段正则校验,C-1)。
- `services/data_pipeline_service/app.py` — 加三端点 + `build_app(uploader=...)` 形参 + `_audit` 通用化。
- `services/data_pipeline_service/main.py` — wiring:构造 `RawDatasetStore` + `Uploader` 传入 `build_app`。

---

## Task 1: 冻结上传契约 + 重生成模型

**Files:**
- Modify: `contracts/openapi/data-pipeline.yaml`
- Modify(生成,勿手改): `libs/contracts_gen/data_pipeline_models.py`
- Test: `tests/test_codegen.py`(已存在;确认 drift 守卫覆盖新模型)

- [x] **Step 1: 在 `data-pipeline.yaml` 的 `paths:` 末尾(`/v1/data/jobs/{job_id}` 之后、`components:` 之前)插入三端点**

```yaml
  /v1/data/raw:
    post:
      summary: 请求上传原始数据(can() 过 → 服务端拼 key → 返回 presigned 直传 URL;ADR-020)
      requestBody: {required: true, content: {application/json: {schema: {$ref: '#/components/schemas/RawUploadRequest'}}}}
      responses:
        '200': {description: grant, content: {application/json: {schema: {$ref: '#/components/schemas/UploadGrant'}}}}
        '400': {description: invalid dataset/filename}
        '401': {description: unauthenticated}
        '403': {description: forbidden}
    get:
      summary: 列本企业/组原始数据集(必经 can() 过滤;分页)
      parameters:
        - {name: status, in: query, required: false, schema: {type: string, enum: [pending, ready, failed]}}
        - {name: limit, in: query, required: false, schema: {type: integer, default: 50, maximum: 200}}
        - {name: offset, in: query, required: false, schema: {type: integer, default: 0}}
      responses:
        '200': {description: list, content: {application/json: {schema: {$ref: '#/components/schemas/RawDatasetList'}}}}
        '401': {description: unauthenticated}
  /v1/data/raw/{raw_id}/complete:
    post:
      summary: 完成上传(入参仅 path id;服务端按记录再 can() + 校验对象;ADR-020 C-2)
      parameters: [{name: raw_id, in: path, required: true, schema: {type: string}}]
      requestBody: {required: false, content: {application/json: {schema: {$ref: '#/components/schemas/CompleteUploadRequest'}}}}
      responses:
        '200': {description: rawdataset, content: {application/json: {schema: {$ref: '#/components/schemas/RawDataset'}}}}
        '403': {description: forbidden}
        '404': {description: not found}
        '409': {description: object missing / complete failed}
```

- [x] **Step 2: 在 `components.schemas:`(`JobList` 之后)追加 schemas**

```yaml
    RawUploadRequest:
      type: object
      required: [dataset, group_id, filename]
      properties:
        dataset: {type: string, pattern: '^[a-z0-9][a-z0-9_-]{0,63}$'}        # 数据集名(=raw 前缀段)
        group_id: {type: string, pattern: '^g-[0-9a-z]+$'}
        filename: {type: string, pattern: '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'}  # 单段文件名(无 '/' → 无穿越)
        multipart: {type: boolean, default: false}
        parts: {type: [integer, 'null'], minimum: 1, maximum: 10000}           # multipart 时分片数
    UploadGrant:
      type: object
      required: [raw_id, oss_key, expires_in]
      properties:
        raw_id: {type: string}
        oss_key: {type: string}
        url: {type: [string, 'null']}                                          # 单传:一条 presigned PUT URL
        upload_id: {type: [string, 'null']}                                    # multipart:OSS UploadId
        part_urls: {type: [array, 'null'], items: {type: string}}             # multipart:逐片 presigned URL(序与 PartNumber 对应)
        expires_in: {type: integer}                                            # 秒,TTL≤900(ADR-020 §4)
    CompletePart:
      type: object
      required: [part_number, etag]
      properties:
        part_number: {type: integer, minimum: 1}
        etag: {type: string}
    CompleteUploadRequest:
      type: object
      properties:
        parts: {type: [array, 'null'], items: {$ref: '#/components/schemas/CompletePart'}}   # 单传留空;multipart 带各片 ETag
    RawDataset:
      type: object
      required: [id, name, group_id, enterprise_id, oss_key, status]
      properties:
        id: {type: string}
        name: {type: string}
        group_id: {type: string, pattern: '^g-[0-9a-z]+$'}
        enterprise_id: {type: string, pattern: '^e-[0-9a-z]+$'}
        oss_key: {type: string}
        status: {type: string, enum: [pending, ready, failed]}
        size: {type: [integer, 'null']}
        error: {type: [string, 'null']}
        created_at: {type: [string, 'null']}
        updated_at: {type: [string, 'null']}
    RawDatasetList:
      type: object
      required: [raw, total]
      properties:
        raw: {type: array, items: {$ref: '#/components/schemas/RawDataset'}}
        total: {type: integer}     # 过滤后(can()+status)总数
```

- [x] **Step 3: 重生成 pydantic 模型**

Run: `make gen`
Expected: 无报错;`libs/contracts_gen/data_pipeline_models.py` 顶部注释不变,新增 `RawUploadRequest`、`UploadGrant`、`CompletePart`、`CompleteUploadRequest`、`RawDataset`、`RawDatasetList` 类。

- [x] **Step 4: 验证模型已生成且可导入**

Run: `uv run python -c "from libs.contracts_gen.data_pipeline_models import RawUploadRequest, UploadGrant, RawDataset, RawDatasetList, CompleteUploadRequest; print('ok')"`
Expected: 打印 `ok`(无 ImportError)。

- [x] **Step 5: 跑既有 codegen drift 守卫确认未漂移**

Run: `uv run pytest tests/test_codegen.py -q`
Expected: PASS(生成产物与契约一致;若该测试比对 `make gen` 输出,确保已提交重生成结果)。

- [x] **Step 6: Commit**

```bash
git add contracts/openapi/data-pipeline.yaml libs/contracts_gen/data_pipeline_models.py
git commit -m "feat(data-pipeline): 冻结上传契约(请求上传/complete/列原始数据)+ 重生成模型 (ADR-020)"
```

---

## Task 2: `raw_object_key` —— 文件名段隔离校验(C-1)

**Files:**
- Modify: `pipelines/data_prep/paths.py:1-8`(加文件名正则)、`:26`(加方法)
- Test: `tests/pipelines/test_paths.py`(若不存在则创建)

- [x] **Step 1: 写失败测试**

创建/追加 `tests/pipelines/test_paths.py`:

```python
import pytest
from libs.identity.ids import EnterpriseId, GroupId
from pipelines.data_prep.paths import DatasetPaths

def _p(dataset="cc3m"):
    return DatasetPaths(bucket="lite-ai", enterprise_id=EnterpriseId("e-0001"),
                        group_id=GroupId("g-0001"), dataset=dataset)

def test_raw_object_key_builds_isolated_path():
    assert _p().raw_object_key("part-0.tar") == "e-0001/g-0001/raw/cc3m/part-0.tar"

@pytest.mark.parametrize("bad", ["../x", "a/b", "/etc/passwd", "..", ".hidden", ""])
def test_raw_object_key_rejects_traversal(bad):
    with pytest.raises(ValueError):
        _p().raw_object_key(bad)
```

- [x] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/pipelines/test_paths.py -q`
Expected: FAIL（`AttributeError: 'DatasetPaths' object has no attribute 'raw_object_key'`）。

- [x] **Step 3: 实现 —— `paths.py` 顶部加文件名正则,类内加方法**

`pipelines/data_prep/paths.py` 第 8 行 `_RE_DATASET = ...` 之后加:

```python
_RE_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")  # 单段文件名,首字符非 '.' → 排除 '..'/'.hidden';无 '/' → 无路径穿越
```

在 `raw_prefix` property 之后加:

```python
    def raw_object_key(self, filename: str) -> str:
        """本组 raw/ 下的完整对象 key。文件名段服务端校验(ADR-020 C-1):
        无 '/' 杜绝路径穿越,首字符非 '.' 杜绝 '..'/隐藏文件。"""
        if not _RE_FILENAME.match(filename):
            raise ValueError(f"invalid filename: {filename!r}")
        return self.raw_prefix + filename
```

- [x] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/pipelines/test_paths.py -q`
Expected: PASS（含全部 parametrize 拒绝用例）。

- [x] **Step 5: Commit**

```bash
git add pipelines/data_prep/paths.py tests/pipelines/test_paths.py
git commit -m "feat(paths): raw_object_key 文件名段隔离校验 (ADR-020 C-1)"
```

---

## Task 3: `RawDatasetStore` —— status-file 持久化(镜像 JobStore)

**Files:**
- Create: `services/data_pipeline_service/raw_store.py`
- Test: `tests/services/data_pipeline/test_raw_store.py`

- [x] **Step 1: 写失败测试**

创建 `tests/services/data_pipeline/test_raw_store.py`:

```python
from services.data_pipeline_service.raw_store import RawSpec, RawDatasetStore

def _spec(rid="raw-1", gid="g-0001", ent="e-0001"):
    return RawSpec(raw_id=rid, name="cc3m", group_id=gid, enterprise_id=ent,
                   sub="u-a", oss_key=f"{ent}/{gid}/raw/cc3m/part-0.tar", upload_id=None)

def test_create_then_read_projects_pending(tmp_path):
    s = RawDatasetStore(str(tmp_path)); s.create(_spec())
    r = s.read("raw-1")
    assert r["status"] == "pending" and r["enterprise_id"] == "e-0001"
    assert r["group_id"] == "g-0001" and r["oss_key"].endswith("raw/cc3m/part-0.tar")
    assert r["size"] is None and r["created_at"]

def test_update_to_ready_sets_size(tmp_path):
    s = RawDatasetStore(str(tmp_path)); s.create(_spec())
    s.update("raw-1", "ready", size=12345)
    r = s.read("raw-1")
    assert r["status"] == "ready" and r["size"] == 12345

def test_read_missing_returns_none(tmp_path):
    assert RawDatasetStore(str(tmp_path)).read("nope") is None

def test_list_raw_returns_projection_with_isolation_fields(tmp_path):
    s = RawDatasetStore(str(tmp_path))
    s.create(_spec("raw-1", "g-0001")); s.create(_spec("raw-2", "g-0002"))
    rows = s.list_raw()
    assert {r["id"] for r in rows} == {"raw-1", "raw-2"}
    assert all("enterprise_id" in r and "group_id" in r for r in rows)   # handler can() 过滤依赖

def test_load_spec_roundtrips_upload_id(tmp_path):
    s = RawDatasetStore(str(tmp_path))
    s.create(RawSpec("raw-m", "cc3m", "g-0001", "e-0001", "u-a", "e-0001/g-0001/raw/cc3m/big.tar", "UP-123"))
    assert s.load_spec("raw-m").upload_id == "UP-123"

def test_delete_removes_record(tmp_path):
    s = RawDatasetStore(str(tmp_path)); s.create(_spec())
    s.delete("raw-1")
    assert s.read("raw-1") is None
```

- [x] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/services/data_pipeline/test_raw_store.py -q`
Expected: FAIL（`ModuleNotFoundError: services.data_pipeline_service.raw_store`）。

- [x] **Step 3: 实现 `raw_store.py`(镜像 `jobs.py` 的原子 status-file 模式)**

```python
from __future__ import annotations
import json, os, shutil
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

_PUBLIC = ("size", "error")   # status.json 上的可投影字段(spec 之外的运行期字段)

@dataclass(frozen=True)
class RawSpec:
    raw_id: str
    name: str
    group_id: str
    enterprise_id: str
    sub: str
    oss_key: str               # 服务端构造、校验过的完整 OSS key(隔离写死)
    upload_id: str | None = None   # multipart 时的 OSS UploadId

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

class RawDatasetStore:
    """状态文件原始数据集存储(ADR-018:v1 无 PG;镜像 JobStore)。spec.json 写一次;
    status.json 走 temp + os.replace 原子替换 —— service 写 pending→ready/failed、
    GC 写删除,读者(list_raw)永不见半写文件。"""
    def __init__(self, root: str):
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=True)

    def raw_dir(self, raw_id: str) -> Path:
        return self.root / raw_id

    def create(self, spec: RawSpec) -> None:
        d = self.raw_dir(spec.raw_id); d.mkdir(parents=True, exist_ok=True)
        (d / "spec.json").write_text(json.dumps(asdict(spec)))
        ts = _now()
        self._write_status(spec.raw_id, {"status": "pending", "created_at": ts, "updated_at": ts,
                                         **{k: None for k in _PUBLIC}})

    def _write_status(self, raw_id: str, status_obj: dict) -> None:
        d = self.raw_dir(raw_id)
        tmp = d / f".status.{os.getpid()}.tmp"
        tmp.write_text(json.dumps(status_obj))
        os.replace(tmp, d / "status.json")

    def update(self, raw_id: str, status: str, **fields) -> None:
        p = self.raw_dir(raw_id) / "status.json"
        cur = json.loads(p.read_text()) if p.exists() else {"created_at": _now(), **{k: None for k in _PUBLIC}}
        cur.update(status=status, updated_at=_now(), **fields)
        self._write_status(raw_id, cur)

    def load_spec(self, raw_id: str) -> RawSpec | None:
        p = self.raw_dir(raw_id) / "spec.json"
        return RawSpec(**json.loads(p.read_text())) if p.exists() else None

    def read(self, raw_id: str) -> dict | None:
        d = self.raw_dir(raw_id)
        if not (d / "status.json").exists():
            return None
        sp = d / "spec.json"
        spec = json.loads(sp.read_text()) if sp.exists() else {}
        st = json.loads((d / "status.json").read_text())
        return {"id": raw_id, "name": spec.get("name"), "group_id": spec.get("group_id"),
                "enterprise_id": spec.get("enterprise_id"), "oss_key": spec.get("oss_key"),
                "status": st["status"], "created_at": st["created_at"], "updated_at": st["updated_at"],
                **{k: st.get(k) for k in _PUBLIC}}

    def list_raw(self) -> list[dict]:
        """纯取数,不授权(授权/过滤在 handler):投影含 enterprise_id/group_id 供 can() 过滤。
        按 created_at 倒序。登记:扫目录 O(n),量大需索引(vN+,S2a 真 store)。"""
        out: list[dict] = []
        for d in self.root.iterdir():
            if not d.is_dir():
                continue
            r = self.read(d.name)
            if r is not None:
                out.append(r)
        out.sort(key=lambda r: r.get("created_at") or "", reverse=True)
        return out

    def delete(self, raw_id: str) -> None:
        shutil.rmtree(self.raw_dir(raw_id), ignore_errors=True)
```

- [x] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/services/data_pipeline/test_raw_store.py -q`
Expected: PASS（6 项）。

- [x] **Step 5: Commit**

```bash
git add services/data_pipeline_service/raw_store.py tests/services/data_pipeline/test_raw_store.py
git commit -m "feat(data-pipeline): RawDatasetStore status-file 持久化 (ADR-018 镜像 JobStore)"
```

---

## Task 4: `Uploader` —— presign / create_grant / finalize / list / gc

**Files:**
- Create: `services/data_pipeline_service/upload.py`
- Test: `tests/services/data_pipeline/test_upload.py`(本任务先写 Uploader 单元,Task 5 复用同文件加端点测试)

测试用 **FakeS3**(实现 boto3 用到的方法子集);不连真 MinIO(那是 Task 7 集成)。

- [x] **Step 1: 写失败测试**

创建 `tests/services/data_pipeline/test_upload.py`:

```python
import pytest
from services.data_pipeline_service.raw_store import RawDatasetStore
from services.data_pipeline_service.upload import Uploader

class FakeS3:
    """boto3 S3 子集 fake:记录调用 + 可控对象存在性。"""
    def __init__(self, existing=None):
        self.existing = dict(existing or {})        # key -> size
        self.aborted = []; self.completed = []
    def generate_presigned_url(self, op, Params, ExpiresIn):
        if op == "put_object":
            return f"https://oss.test/{Params['Key']}?sig=single"
        if op == "upload_part":
            return f"https://oss.test/{Params['Key']}?partNumber={Params['PartNumber']}&uploadId={Params['UploadId']}&sig=part"
        raise AssertionError(op)
    def create_multipart_upload(self, Bucket, Key, **kw):
        return {"UploadId": "UP-1"}
    def complete_multipart_upload(self, Bucket, Key, UploadId, MultipartUpload):
        self.completed.append((Key, UploadId)); self.existing[Key] = 999
        return {}
    def abort_multipart_upload(self, Bucket, Key, UploadId):
        self.aborted.append((Key, UploadId))
    def head_object(self, Bucket, Key):
        if Key not in self.existing:
            from botocore.exceptions import ClientError
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        return {"ContentLength": self.existing[Key]}

def _uploader(tmp_path, s3):
    return Uploader(raw_store=RawDatasetStore(str(tmp_path)), s3=s3, data_bucket="lite-ai", url_ttl=900)

def test_create_grant_single_builds_isolated_key_and_url(tmp_path):
    up = _uploader(tmp_path, FakeS3())
    g = up.create_grant(name="cc3m", enterprise_id="e-0001", group_id="g-0001",
                        sub="u-a", filename="part-0.tar", multipart=False, parts=None)
    assert g["oss_key"] == "e-0001/g-0001/raw/cc3m/part-0.tar"
    assert g["url"] and g["upload_id"] is None and g["part_urls"] is None and g["expires_in"] == 900
    rec = up.get_record(g["raw_id"])
    assert rec["status"] == "pending" and rec["enterprise_id"] == "e-0001"   # 记录已建

def test_create_grant_rejects_bad_filename_no_record(tmp_path):
    up = _uploader(tmp_path, FakeS3())
    with pytest.raises(ValueError):
        up.create_grant(name="cc3m", enterprise_id="e-0001", group_id="g-0001",
                        sub="u-a", filename="../escape", multipart=False, parts=None)
    assert up.list_raw() == []     # 零副作用:校验失败不建记录

def test_create_grant_multipart_presigns_each_part(tmp_path):
    up = _uploader(tmp_path, FakeS3())
    g = up.create_grant(name="cc3m", enterprise_id="e-0001", group_id="g-0001",
                        sub="u-a", filename="big.tar", multipart=True, parts=3)
    assert g["upload_id"] == "UP-1" and len(g["part_urls"]) == 3 and g["url"] is None
    assert up.get_record(g["raw_id"])  # pending 记录含 upload_id
    assert up.raw_store.load_spec(g["raw_id"]).upload_id == "UP-1"

def test_finalize_single_marks_ready_with_size(tmp_path):
    s3 = FakeS3()
    up = _uploader(tmp_path, s3)
    g = up.create_grant(name="cc3m", enterprise_id="e-0001", group_id="g-0001",
                        sub="u-a", filename="part-0.tar", multipart=False, parts=None)
    s3.existing[g["oss_key"]] = 4096       # 模拟客户端已直传
    out = up.finalize(g["raw_id"], parts=None)
    assert out["status"] == "ready" and out["size"] == 4096

def test_finalize_object_missing_raises_objectmissing(tmp_path):
    up = _uploader(tmp_path, FakeS3())     # 对象不存在
    g = up.create_grant(name="cc3m", enterprise_id="e-0001", group_id="g-0001",
                        sub="u-a", filename="part-0.tar", multipart=False, parts=None)
    from services.data_pipeline_service.upload import ObjectMissing
    with pytest.raises(ObjectMissing):
        up.finalize(g["raw_id"], parts=None)
    assert up.get_record(g["raw_id"])["status"] == "failed"   # 标 failed

def test_finalize_multipart_completes_then_ready(tmp_path):
    s3 = FakeS3()
    up = _uploader(tmp_path, s3)
    g = up.create_grant(name="cc3m", enterprise_id="e-0001", group_id="g-0001",
                        sub="u-a", filename="big.tar", multipart=True, parts=2)
    out = up.finalize(g["raw_id"], parts=[{"part_number": 1, "etag": "e1"}, {"part_number": 2, "etag": "e2"}])
    assert out["status"] == "ready" and (g["oss_key"], "UP-1") in s3.completed

def test_gc_aborts_multipart_and_deletes_stale_pending(tmp_path):
    s3 = FakeS3()
    up = _uploader(tmp_path, s3)
    g = up.create_grant(name="cc3m", enterprise_id="e-0001", group_id="g-0001",
                        sub="u-a", filename="big.tar", multipart=True, parts=2)
    reaped = up.gc(ttl_seconds=0)           # ttl=0 → 立即视为超时
    assert g["raw_id"] in reaped
    assert (g["oss_key"], "UP-1") in s3.aborted   # 孤儿分片 abort(防漏钱)
    assert up.get_record(g["raw_id"]) is None      # 记录已删
```

- [x] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/services/data_pipeline/test_upload.py -q`
Expected: FAIL（`ModuleNotFoundError: services.data_pipeline_service.upload`）。

- [x] **Step 3: 实现 `upload.py`**

```python
from __future__ import annotations
import uuid
from datetime import datetime, timezone

from botocore.exceptions import ClientError

from libs.identity.ids import EnterpriseId, GroupId
from pipelines.data_prep.paths import DatasetPaths
from services.data_pipeline_service.raw_store import RawSpec, RawDatasetStore


class ObjectMissing(Exception):
    """complete 时 OSS 上对象不存在 / 分片合并失败 → handler 映射 409。"""


def _now_epoch() -> float:
    return datetime.now(timezone.utc).timestamp()


class Uploader:
    """上传机制封装(ADR-020):key 服务端构造写死、presign 单/分片、complete 校验、GC。
    基础设施无感(持 raw_store + s3 + bucket),仿 runner 注入 build_app。授权(can())留在 handler。"""

    def __init__(self, raw_store: RawDatasetStore, s3, data_bucket: str, url_ttl: int = 900):
        self.raw_store = raw_store
        self.s3 = s3
        self.bucket = data_bucket
        self.url_ttl = url_ttl

    # ---- 请求上传:建记录 + presign ----
    def create_grant(self, *, name: str, enterprise_id: str, group_id: str, sub: str,
                     filename: str, multipart: bool, parts: int | None) -> dict:
        # key 三段服务端构造(C-1):eid/gid 来自调用者(handler 取自 ctx),dataset/filename 经校验。
        paths = DatasetPaths(bucket=self.bucket, enterprise_id=EnterpriseId(enterprise_id),
                             group_id=GroupId(group_id), dataset=name)   # DatasetPaths 校验 dataset
        oss_key = paths.raw_object_key(filename)                         # 校验 filename(失败抛 ValueError,零副作用)
        raw_id = "raw-" + uuid.uuid4().hex[:16]
        if multipart:
            n = parts or 1
            up = self.s3.create_multipart_upload(Bucket=self.bucket, Key=oss_key)
            upload_id = up["UploadId"]
            part_urls = [self.s3.generate_presigned_url(
                "upload_part",
                Params={"Bucket": self.bucket, "Key": oss_key, "UploadId": upload_id, "PartNumber": i},
                ExpiresIn=self.url_ttl) for i in range(1, n + 1)]
            url = None
        else:
            upload_id = None; part_urls = None
            url = self.s3.generate_presigned_url(
                "put_object", Params={"Bucket": self.bucket, "Key": oss_key}, ExpiresIn=self.url_ttl)
        self.raw_store.create(RawSpec(raw_id=raw_id, name=name, group_id=group_id,
                                      enterprise_id=enterprise_id, sub=sub, oss_key=oss_key, upload_id=upload_id))
        return {"raw_id": raw_id, "oss_key": oss_key, "url": url,
                "upload_id": upload_id, "part_urls": part_urls, "expires_in": self.url_ttl}

    def get_record(self, raw_id: str) -> dict | None:
        return self.raw_store.read(raw_id)

    # ---- 完成:校验对象 → ready/failed(key 从记录取,不信请求体;C-2)----
    def finalize(self, raw_id: str, parts: list[dict] | None) -> dict:
        spec = self.raw_store.load_spec(raw_id)
        if spec is None:
            raise ObjectMissing("record not found")
        key = spec.oss_key
        try:
            if spec.upload_id:
                mp = {"Parts": [{"ETag": p["etag"], "PartNumber": p["part_number"]}
                                for p in sorted(parts or [], key=lambda p: p["part_number"])]}
                self.s3.complete_multipart_upload(Bucket=self.bucket, Key=key,
                                                  UploadId=spec.upload_id, MultipartUpload=mp)
            head = self.s3.head_object(Bucket=self.bucket, Key=key)   # 仅证存在 + 取 size
        except (ClientError, KeyError) as e:
            self.raw_store.update(raw_id, "failed", error=str(e))
            raise ObjectMissing(str(e))
        self.raw_store.update(raw_id, "ready", size=head.get("ContentLength"))
        return self.raw_store.read(raw_id)

    def list_raw(self) -> list[dict]:
        return self.raw_store.list_raw()

    # ---- GC:清超时 pending + abort 孤儿分片 + 对账(ADR-020 §3 / I-2)----
    def gc(self, ttl_seconds: int) -> list[str]:
        reaped: list[str] = []
        now = _now_epoch()
        for rec in self.raw_store.list_raw():
            if rec["status"] != "pending":
                continue
            created = rec.get("created_at")
            try:
                age = now - datetime.fromisoformat(created).timestamp() if created else ttl_seconds + 1
            except ValueError:
                age = ttl_seconds + 1
            if age < ttl_seconds:
                continue
            spec = self.raw_store.load_spec(rec["id"])
            if spec and spec.upload_id:                 # 孤儿 multipart → abort(防 OSS 计费分片漏钱)
                try:
                    self.s3.abort_multipart_upload(Bucket=self.bucket, Key=spec.oss_key, UploadId=spec.upload_id)
                except ClientError:
                    pass
            self.raw_store.delete(rec["id"])
            reaped.append(rec["id"])
        return reaped
```

- [x] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/services/data_pipeline/test_upload.py -q`
Expected: PASS（7 项 Uploader 单元）。

- [x] **Step 5: Commit**

```bash
git add services/data_pipeline_service/upload.py tests/services/data_pipeline/test_upload.py
git commit -m "feat(data-pipeline): Uploader presign/complete/list/gc (ADR-020 C-1/C-2/§3)"
```

---

## Task 5: 三端点接入 `app.py` + wiring

**Files:**
- Modify: `services/data_pipeline_service/app.py`(加 `_audit` 通用化 + 三 handler + `build_app(uploader=None)`)
- Modify: `services/data_pipeline_service/main.py`(构造 Uploader 注入)
- Test: `tests/services/data_pipeline/test_upload.py`(追加端点测试)

- [x] **Step 1: 写失败测试(追加到 `test_upload.py` 末尾)**

```python
import json
from fastapi.testclient import TestClient
from services.data_pipeline_service.app import build_app
from libs.audit.oss_audit import AuditWriter

class MemSink:
    def __init__(self): self.items = []
    def put(self, key, body): self.items.append((key, body))

def _client(tmp_path, s3, monkeypatch):
    monkeypatch.setenv("LITEAI_ALLOW_TEST_CLAIMS", "1")
    sink = MemSink()
    up = _uploader(tmp_path, s3)
    runner = None   # 上传端点不依赖 runner
    return TestClient(build_app(runner=runner, audit=AuditWriter(sink), uploader=up)), up, sink

def _hdr(sub, groups): return {"x-test-claims": json.dumps({"sub": sub, "groups": groups})}

def test_request_upload_returns_grant(tmp_path, monkeypatch):
    c, up, _ = _client(tmp_path, FakeS3(), monkeypatch)
    r = c.post("/v1/data/raw", headers=_hdr("u-a", ["/e-0001/g-0001/members"]),
               json={"dataset": "cc3m", "group_id": "g-0001", "filename": "part-0.tar"})
    assert r.status_code == 200
    g = r.json()
    assert g["oss_key"] == "e-0001/g-0001/raw/cc3m/part-0.tar" and g["url"]

def test_request_upload_cross_group_403_no_record_audited(tmp_path, monkeypatch):
    c, up, sink = _client(tmp_path, FakeS3(), monkeypatch)
    r = c.post("/v1/data/raw", headers=_hdr("u-x", ["/e-0001/g-0002/members"]),
               json={"dataset": "cc3m", "group_id": "g-0001", "filename": "part-0.tar"})
    assert r.status_code == 403
    assert up.list_raw() == []                                   # 零副作用
    assert json.loads(sink.items[0][1])["decision"] == "deny"    # deny 审计

def test_request_upload_bad_filename_400(tmp_path, monkeypatch):
    c, up, _ = _client(tmp_path, FakeS3(), monkeypatch)
    r = c.post("/v1/data/raw", headers=_hdr("u-a", ["/e-0001/g-0001/members"]),
               json={"dataset": "cc3m", "group_id": "g-0001", "filename": "../escape"})
    assert r.status_code == 400 and up.list_raw() == []

def test_complete_only_by_id_marks_ready(tmp_path, monkeypatch):
    s3 = FakeS3(); c, up, _ = _client(tmp_path, s3, monkeypatch)
    g = c.post("/v1/data/raw", headers=_hdr("u-a", ["/e-0001/g-0001/members"]),
               json={"dataset": "cc3m", "group_id": "g-0001", "filename": "part-0.tar"}).json()
    s3.existing[g["oss_key"]] = 4096                              # 模拟已直传
    r = c.post(f"/v1/data/raw/{g['raw_id']}/complete", headers=_hdr("u-a", ["/e-0001/g-0001/members"]), json={})
    assert r.status_code == 200 and r.json()["status"] == "ready" and r.json()["size"] == 4096

def test_complete_cross_group_403(tmp_path, monkeypatch):
    s3 = FakeS3(); c, up, _ = _client(tmp_path, s3, monkeypatch)
    g = c.post("/v1/data/raw", headers=_hdr("u-a", ["/e-0001/g-0001/members"]),
               json={"dataset": "cc3m", "group_id": "g-0001", "filename": "part-0.tar"}).json()
    s3.existing[g["oss_key"]] = 4096
    r = c.post(f"/v1/data/raw/{g['raw_id']}/complete",        # 另一组用户拿到 id 也不行
               headers=_hdr("u-b", ["/e-0001/g-0002/members"]), json={})
    assert r.status_code == 403

def test_complete_object_missing_409(tmp_path, monkeypatch):
    c, up, _ = _client(tmp_path, FakeS3(), monkeypatch)        # 对象从未上传
    g = c.post("/v1/data/raw", headers=_hdr("u-a", ["/e-0001/g-0001/members"]),
               json={"dataset": "cc3m", "group_id": "g-0001", "filename": "part-0.tar"}).json()
    r = c.post(f"/v1/data/raw/{g['raw_id']}/complete", headers=_hdr("u-a", ["/e-0001/g-0001/members"]), json={})
    assert r.status_code == 409

def test_complete_unknown_id_404(tmp_path, monkeypatch):
    c, up, _ = _client(tmp_path, FakeS3(), monkeypatch)
    r = c.post("/v1/data/raw/nope/complete", headers=_hdr("u-a", ["/e-0001/g-0001/members"]), json={})
    assert r.status_code == 404

def test_list_raw_can_filter_cross_group_hidden(tmp_path, monkeypatch):
    c, up, _ = _client(tmp_path, FakeS3(), monkeypatch)
    c.post("/v1/data/raw", headers=_hdr("u-a", ["/e-0001/g-0001/members"]),
           json={"dataset": "cc3m", "group_id": "g-0001", "filename": "a.tar"})
    rows = c.get("/v1/data/raw", headers=_hdr("u-b", ["/e-0001/g-0002/members"])).json()
    assert rows["raw"] == [] and rows["total"] == 0             # 跨组不可见
    own = c.get("/v1/data/raw", headers=_hdr("u-a", ["/e-0001/g-0001/members"])).json()
    assert own["total"] == 1 and own["raw"][0]["group_id"] == "g-0001"
```

- [x] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/services/data_pipeline/test_upload.py -q`
Expected: FAIL（`build_app() got an unexpected keyword argument 'uploader'`）。

- [x] **Step 3: 改 `app.py` —— `_audit` 通用化 + `build_app(uploader=None)` + 三 handler**

把 `app.py:16-20` 的 `_audit_deny` 替换为通用 `_audit`(兼容既有 prepare 调用):

```python
def _audit(audit: AuditWriter, ctx: Context, ent: str, gid: str, resource_uri: str,
           action: str, decision: str, reason: str) -> None:
    audit.write(AuditEvent(ts=datetime.now(timezone.utc).isoformat(), enterprise_id=ent, group_id=gid,
                           actor_user=ctx.user, actor_role=ctx.role_in(EnterpriseId(ent), GroupId(gid)) or "none",
                           action=action, resource_uri=resource_uri, decision=decision,
                           override=False, reason=reason, metadata={}))
```

并把 prepare 里原 `_audit_deny(audit, ctx, ent, body.group_id, body.dataset, d.reason)` 改为:

```python
            _audit(audit, ctx, ent, body.group_id, f"dataset/{body.dataset}", "data.prepare", "deny", d.reason)
```

改 `build_app` 签名为 `def build_app(runner, audit: AuditWriter, uploader=None):`,在 `return app` 之前插入三 handler:

```python
    @app.post("/v1/data/raw")
    def request_upload(body: RawUploadRequest, ctx: Context = Depends(context_from_request)):
        if uploader is None:
            raise HTTPException(status_code=503, detail="upload not configured")
        ent = enterprise_of(ctx)
        res = Resource(kind="dataset", enterprise_id=EnterpriseId(ent), group_id=GroupId(body.group_id))
        d = can(ctx, "data.upload", res)
        if not d.allow:                                       # deny → 零副作用 + 审计
            _audit(audit, ctx, ent, body.group_id, f"raw/{body.dataset}", "data.upload", "deny", d.reason)
            return JSONResponse(status_code=403, content={"reason": d.reason})
        try:
            grant = uploader.create_grant(name=body.dataset, enterprise_id=ent, group_id=body.group_id,
                                          sub=ctx.user, filename=body.filename,
                                          multipart=bool(body.multipart), parts=body.parts)
        except ValueError as e:                               # 文件名/数据集名非法
            return JSONResponse(status_code=400, content={"reason": str(e)})
        _audit(audit, ctx, ent, body.group_id, f"raw/{body.dataset}", "data.upload", "allow", "")
        return grant

    @app.post("/v1/data/raw/{raw_id}/complete")
    def complete_upload(raw_id: str, body: CompleteUploadRequest | None = None,
                        ctx: Context = Depends(context_from_request)):
        if uploader is None:
            raise HTTPException(status_code=503, detail="upload not configured")
        ent = enterprise_of(ctx)
        rec = uploader.get_record(raw_id)
        if rec is None or rec["enterprise_id"] != ent:        # 跨企业=不存在(不泄漏)
            raise HTTPException(status_code=404, detail="not found")
        res = Resource(kind="dataset", enterprise_id=EnterpriseId(ent), group_id=GroupId(rec["group_id"]))
        if not can(ctx, "data.upload", res).allow:            # 按记录 eid/gid 再 can()(C-2)
            return JSONResponse(status_code=403, content={"reason": "cross-group"})
        parts = [p.model_dump() for p in (body.parts or [])] if body and body.parts else None
        try:
            out = uploader.finalize(raw_id, parts=parts)
        except ObjectMissing as e:
            _audit(audit, ctx, ent, rec["group_id"], f"raw/{rec['name']}", "data.upload", "deny", "object-missing")
            return JSONResponse(status_code=409, content={"reason": str(e)})
        _audit(audit, ctx, ent, rec["group_id"], f"raw/{rec['name']}", "data.upload", "allow", "complete")
        return out

    @app.get("/v1/data/raw")
    def list_raw(status: str | None = None,
                 limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                 ctx: Context = Depends(context_from_request)):
        if uploader is None:
            raise HTTPException(status_code=503, detail="upload not configured")
        ent = enterprise_of(ctx)
        visible = []
        for r in uploader.list_raw():
            re_, rg = r.get("enterprise_id"), r.get("group_id")
            if re_ is None or re_ != ent:                     # fail-closed:缺失/跨企业 → 跳过
                continue
            res = Resource(kind="dataset", enterprise_id=EnterpriseId(ent), group_id=GroupId(rg))
            if not can(ctx, "data.read", res).allow:          # 必经 can() 按组过滤
                continue
            if status and r.get("status") != status:
                continue
            visible.append(r)
        return {"raw": visible[offset: offset + limit], "total": len(visible)}
```

在 `app.py` 顶部 import 段补:

```python
from libs.contracts_gen.data_pipeline_models import (
    PrepareJobRequest, RawUploadRequest, CompleteUploadRequest)
from services.data_pipeline_service.upload import ObjectMissing
```

(把原 `from libs.contracts_gen.data_pipeline_models import PrepareJobRequest` 替换为上面这行;保留其余 import 不变。)

- [x] **Step 4: 改 `main.py` —— 构造 Uploader 注入 `build_app`**

把 `main.py` 末尾两行(`_runner = ...` 与 `app = build_app(...)`)之间/之后改为:

```python
from services.data_pipeline_service.raw_store import RawDatasetStore
from services.data_pipeline_service.upload import Uploader

_runner = SubprocessJobRunner(JobStore(os.environ.get("JOBS_DIR", "./.jobs")), dispatch_interval=2.0)
_uploader = Uploader(raw_store=RawDatasetStore(os.environ.get("RAW_DIR", "./.raw")),
                     s3=_s3, data_bucket=os.environ["DATA_BUCKET"],
                     url_ttl=int(os.getenv("UPLOAD_URL_TTL", "900")))
app = build_app(runner=_runner, audit=AuditWriter(OssAuditSink(bucket=os.environ["AUDIT_BUCKET"], client=_s3)),
                uploader=_uploader)
```

- [x] **Step 5: 跑全套单元测试确认通过(含既有 prepare/jobs 测试未被破坏)**

Run: `uv run pytest tests/services/data_pipeline/ -q`
Expected: PASS（含 `test_app.py` 既有用例 —— `_audit` 改名后 deny 审计仍写出,既有断言 `decision=="deny"` 不变）。

- [x] **Step 6: Commit**

```bash
git add services/data_pipeline_service/app.py services/data_pipeline_service/main.py tests/services/data_pipeline/test_upload.py
git commit -m "feat(data-pipeline): 上传三端点接入 app + wiring (ADR-020)"
```

---

## Task 6: GC 入口脚本(运维可调度)

**Files:**
- Create: `scripts/raw_gc.py`(一次性 GC 调用;调度周期留运维 cron,ADR-020 §3)
- Test: GC 逻辑已在 Task 4 `test_gc_aborts_multipart_and_deletes_stale_pending` 覆盖;本任务只加可执行入口 + 冒烟。

- [x] **Step 1: 实现 `scripts/raw_gc.py`**

```python
"""清理超时未完成的 pending 原始上传(ADR-020 §3):abort 孤儿分片 + 删记录。
运维按需 cron:`uv run python scripts/raw_gc.py`。周期/TTL 由 env 控,非本地阻塞。"""
import os, sys
import boto3
from libs.audit.oss_audit import oss_boto3_config
from services.data_pipeline_service.raw_store import RawDatasetStore
from services.data_pipeline_service.upload import Uploader

def main() -> int:
    endpoint = os.environ["OSS_ENDPOINT"]
    s3 = boto3.client("s3", endpoint_url=endpoint, aws_access_key_id=os.environ["OSS_ACCESS_KEY"],
                      aws_secret_access_key=os.environ["OSS_SECRET_KEY"],
                      aws_session_token=os.getenv("OSS_SESSION_TOKEN"),
                      region_name=os.getenv("OSS_REGION", "cn-hangzhou"), config=oss_boto3_config(endpoint))
    up = Uploader(raw_store=RawDatasetStore(os.environ.get("RAW_DIR", "./.raw")),
                  s3=s3, data_bucket=os.environ["DATA_BUCKET"])
    ttl = int(os.getenv("RAW_PENDING_TTL", "3600"))
    reaped = up.gc(ttl_seconds=ttl)
    print(f"raw_gc: reaped {len(reaped)} stale pending: {reaped}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

- [x] **Step 2: 冒烟(导入即可,不连真 OSS)**

Run: `uv run python -c "import scripts.raw_gc; print('ok')"`
Expected: 打印 `ok`（仅导入,不执行 main → 不需要 env/OSS）。

- [x] **Step 3: Commit**

```bash
git add scripts/raw_gc.py
git commit -m "feat(data-pipeline): raw_gc 运维 GC 入口 (ADR-020 §3)"
```

---

## Task 7: 集成测试 —— 真 MinIO presigned 端到端

**Files:**
- Create: `tests/integration/test_raw_upload_e2e.py`(`@pytest.mark.integration`)

验证探查链路在**真服务端口**重现:请求上传 → httpx 直 PUT presigned URL → complete → list 见 ready。

- [x] **Step 1: 写测试**

```python
import json, httpx, pytest
from fastapi.testclient import TestClient
from libs.audit.oss_audit import AuditWriter
from services.data_pipeline_service.app import build_app
from services.data_pipeline_service.raw_store import RawDatasetStore
from services.data_pipeline_service.upload import Uploader

pytestmark = pytest.mark.integration

class MemSink:
    def __init__(self): self.items = []
    def put(self, key, body): self.items.append((key, body))

def _hdr(sub, groups): return {"x-test-claims": json.dumps({"sub": sub, "groups": groups})}

def test_presigned_single_roundtrip_on_minio(tmp_path, minio_s3, minio_bucket, monkeypatch):
    monkeypatch.setenv("LITEAI_ALLOW_TEST_CLAIMS", "1")
    up = Uploader(raw_store=RawDatasetStore(str(tmp_path)), s3=minio_s3, data_bucket=minio_bucket, url_ttl=900)
    c = TestClient(build_app(runner=None, audit=AuditWriter(MemSink()), uploader=up))

    g = c.post("/v1/data/raw", headers=_hdr("u-a", ["/e-0001/g-0001/members"]),
               json={"dataset": "cc3m", "group_id": "g-0001", "filename": "part-0.bin"}).json()
    assert g["oss_key"] == "e-0001/g-0001/raw/cc3m/part-0.bin"

    body = b"hello-raw" * 1000
    put = httpx.put(g["url"], content=body, timeout=30)           # 纯 PUT 模拟浏览器直传
    assert put.status_code in (200, 201)

    out = c.post(f"/v1/data/raw/{g['raw_id']}/complete",
                 headers=_hdr("u-a", ["/e-0001/g-0001/members"]), json={}).json()
    assert out["status"] == "ready" and out["size"] == len(body)

    lst = c.get("/v1/data/raw", headers=_hdr("u-a", ["/e-0001/g-0001/members"])).json()
    assert lst["total"] == 1 and lst["raw"][0]["status"] == "ready"

def test_presigned_multipart_roundtrip_on_minio(tmp_path, minio_s3, minio_bucket, monkeypatch):
    monkeypatch.setenv("LITEAI_ALLOW_TEST_CLAIMS", "1")
    up = Uploader(raw_store=RawDatasetStore(str(tmp_path)), s3=minio_s3, data_bucket=minio_bucket, url_ttl=900)
    c = TestClient(build_app(runner=None, audit=AuditWriter(MemSink()), uploader=up))

    g = c.post("/v1/data/raw", headers=_hdr("u-a", ["/e-0001/g-0001/members"]),
               json={"dataset": "cc3m", "group_id": "g-0001", "filename": "big.bin",
                     "multipart": True, "parts": 2}).json()
    part = b"x" * (5 * 1024 * 1024)                               # 5 MiB(分片下限)
    etags = []
    for i, url in enumerate(g["part_urls"], start=1):
        r = httpx.put(url, content=part, timeout=120)
        assert r.status_code in (200, 201)
        etags.append({"part_number": i, "etag": r.headers["ETag"]})
    out = c.post(f"/v1/data/raw/{g['raw_id']}/complete",
                 headers=_hdr("u-a", ["/e-0001/g-0001/members"]),
                 json={"parts": etags}).json()
    assert out["status"] == "ready" and out["size"] == len(part) * 2
```

- [x] **Step 2: 确保 dev 服务在跑后执行集成测试**

Run: `make dev-up && uv run pytest tests/integration/test_raw_upload_e2e.py -q -m integration`
Expected: PASS（2 项;若 MinIO 未起,fixture `minio_s3` 自动 skip 而非 fail）。

- [x] **Step 3: Commit**

```bash
git add tests/integration/test_raw_upload_e2e.py
git commit -m "test(data-pipeline): 真 MinIO presigned 单/分片端到端集成 (探查 spikes/oss_upload 重现)"
```

---

## Task 8: 全绿门禁 + 手动验收 runbook(ADR-015)

**Files:**
- 无新代码;跑仓库全绿门禁 + 补 runbook 段。

- [x] **Step 1: 按 CLAUDE.md 跑全绿门禁**

Run: `make gen && make lint && uv run pytest -q`(以仓库 `Makefile`/`CLAUDE.md` 定义的"全绿"为准)
Expected: 全绿;契约无 drift(`tests/test_codegen.py`)、既有 data_pipeline 测试不破。

- [x] **Step 2: 把下方"手动验收 runbook"段确认已在本 plan(见文末),执行一次留痕**

(runbook 见文末 ## 手动验收 runbook;owner/执行者按步骤过一遍,勾选实时状态 ADR-017。)

- [x] **Step 3: 最终 Commit(若 lint 有自动修正)**

```bash
git add -A
git commit -m "chore(data-pipeline): 全绿门禁 + 上传后端验收留痕"
```

---

## 手动验收 runbook(ADR-015;dev 真服务,人工过一遍)

> 前置:`make dev-up`(起 MinIO/Keycloak)。服务可用 `uvicorn services.data_pipeline_service.main:app --port 8003` 起(需 env:`OSS_ENDPOINT/OSS_ACCESS_KEY/OSS_SECRET_KEY/DATA_BUCKET/AUDIT_BUCKET`)。鉴权可用集成测试的 `x-test-claims`(设 `LITEAI_ALLOW_TEST_CLAIMS=1`)或真 Keycloak token。

- [ ] **R1 请求上传(本组)**:`POST /v1/data/raw` body `{"dataset":"cc3m","group_id":"g-0001","filename":"a.bin"}` → 200,返回 `oss_key=e-0001/g-0001/raw/cc3m/a.bin` + `url`。
- [ ] **R2 直传 OSS**:对 R1 的 `url` 做 `curl -X PUT --data-binary @a.bin "<url>"` → 200/201;MinIO 控制台(:9001)能看到对象落在 `raw/cc3m/`。
- [ ] **R3 完成**:`POST /v1/data/raw/{raw_id}/complete` body `{}` → 200 `status=ready`、`size` 与文件一致。
- [ ] **R4 列原始数据**:`GET /v1/data/raw` → 见该 ready 记录;换**别组**身份(`g-0002`)`GET` → 不出现(can() 过滤)。
- [ ] **R5 隔离命门 C-1**:`POST /v1/data/raw` 用 `g-0002` 身份传 `group_id=g-0001` → **403** + 审计 deny + 无记录。
- [ ] **R6 隔离命门 C-2**:别组身份对 R1 的 `raw_id` 调 complete → **403**(拿到 id 也越不了权)。
- [ ] **R7 文件名穿越**:`filename="../escape"` → **400**,无记录。
- [ ] **R8 对象缺失**:请求上传后**不**直传,直接 complete → **409**,记录 `failed`。
- [ ] **R9 大文件分片**:`multipart:true,parts:2` 请求 → 逐片 PUT(各 ≥5MiB)→ complete 带 ETags → `ready`。
- [ ] **R10 GC**:造一条 pending(请求上传不 complete),`RAW_PENDING_TTL=0 uv run python scripts/raw_gc.py` → 记录被清;multipart 的孤儿分片被 abort。

> **prod 上线 DoD 硬门(非本地可测,显式登记;ADR-020 §5/§6)**:① 阿里云 OSS bucket 配 **CORS**(允许前端域名 Origin、`PUT`、暴露 `ETag`);② **virtual-hosted addressing + multipart ETag 行为 staging 复验**;③ prod OSS 域名进前端 **CSP `connect-src`**。漏了 prod 上传必跨域失败。

---

## Self-Review

- **Spec 覆盖**:FR-001(presign 时 can()+deny 审计)→ Task5 request_upload;FR-002(key 三段服务端钉死)→ Task2 + Task4 create_grant;FR-003(complete 仅 id + 再 can() + head_object)→ Task5 complete_upload + Task4 finalize;FR-004(list can() 过滤 + 分页)→ Task5 list_raw;FR-005(状态机 + GC abort 孤儿 + 对账)→ Task3/4/6;FR-006(TTL≤15min)→ Uploader `url_ttl=900` + main 注入;FR-007(mutation 审计)→ `_audit` allow/deny 两点。AC-1~7 → Task5/7 测试 + runbook R1~R10。
- **占位符扫描**:无 TBD;每步含可运行命令 + 期望输出 + 完整代码。
- **类型一致性**:`Uploader.create_grant(name=…,enterprise_id=…,group_id=…,sub=…,filename=…,multipart=…,parts=…)` 在 Task4 定义、Task5 handler 同签名调用;`RawSpec` 字段(raw_id/name/group_id/enterprise_id/sub/oss_key/upload_id)Task3 定义、Task4 构造一致;契约 schema 字段(dataset/group_id/filename/multipart/parts;raw_id/oss_key/url/upload_id/part_urls/expires_in)Task1 定义、Task4 返回 dict 同名。
