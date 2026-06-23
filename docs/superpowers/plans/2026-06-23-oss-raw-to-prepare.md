> ⚠️ **SUPERSEDED by [2026-06-23-catalog-driven-datasets.md](./2026-06-23-catalog-driven-datasets.md)**(owner 选 catalog-driven 模型;本 plan 的 fetch_oss_tars 机制已并入,'约定读'换成 catalog-driven 读)。

# 打通 OSS→管线(S2a raw→prepare)Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development(推荐)或 superpowers:executing-plans 逐任务执行。步骤用 checkbox(`- [ ]`)跟踪。

**Goal:** 让数据准备作业能**直接从对象存储(OSS)读已上传的 raw 数据集**跑管线(不再手填本地 ops 路径),并把"上传→从OSS跑管线→注册到数据目录"全链路在本地跑通。

**Architecture:** `prepare` 的 `tar_dir` 改可选;缺省时 `run_prepare` 按调用者身份(ctx 钉死的 enterprise_id)+ group_id + dataset 用现成的 `DatasetPaths.raw_prefix` 拼出 OSS 前缀 `{eid}/{gid}/raw/{dataset}/`,新 helper `fetch_oss_tars` 用 boto3 把该前缀下的 `*.tar` 下载到本地临时目录,再喂**现有** `wds_to_jsonl`(本地读,不改)。隔离:前缀只来自身份,**不收客户端任意 OSS 路径**(细粒度权限留 Cerbos,本轮不碰)。顺带补两个让全链路通的缺口:注册自动建 catalog/schema、列表 404→空。前端 CreateJob 把"源"从手填路径换成"已上传 raw 数据集"下拉。

**Tech Stack:** Python(boto3 复用 `libs/audit/oss_audit.py:oss_boto3_config`)、Data-Juicer(`.dj-venv`)、FastAPI、Gravitino、React/Vite + vitest、pytest。

**地基/依据:** ADR-018(tar_dir → S2a 解析 OSS raw 引用,**本计划即执行此预告,无新 ADR**)、ADR-020(key 服务端钉死的隔离范式)。**不开 spec**(比例原则:设计无分叉、执行既定演进)。

**分支:** 从 `s1-plan8b-frontend` 拉 `oss-raw-to-prepare`(因前端 CreateJob 只存在于该分支)。

**前置(执行 e2e 前):** `make dj-setup`(建 `.dj-venv/bin/dj-process`);`make deps-dev`(MinIO+Keycloak+Postgres+Gravitino);bootstrap 后端服务起着。

---

## File Structure
| 文件 | 责任 | 动作 |
|---|---|---|
| `pipelines/data_prep/oss_fetch.py` | `fetch_oss_tars`:列+下载 OSS 前缀下 *.tar 到本地 | Create |
| `pipelines/data_prep/runner.py` | `run_prepare`:tar_dir 缺省 → 拼 OSS 前缀 + fetch → wds_to_jsonl | Modify |
| `contracts/openapi/data-pipeline.yaml` | `PrepareJobRequest.tar_dir` 改可选 | Modify |
| `services/data_pipeline_service/app.py` | prepare 端点透传可选 tar_dir | Modify |
| `services/data_pipeline_service/worker.py` / `runner` JobSpec/PrepareRequest | tar_dir 可选 | Modify |
| `services/metadata_service/app.py` | 注册自动 ensure_catalog/schema;list_ds 404→空 | Modify |
| `frontend/src/pages/CreateJob.tsx` + `frontend/src/api/jobs.ts` | 源 = 已上传 raw 数据集下拉 | Modify |
| `scripts/make_coco_smoke_tar.py` | 取 coco-30-val ~64 条打包 webdataset tar(e2e 夹具) | Create |
| `tests/pipelines/test_oss_fetch.py` / `tests/pipelines/test_runner_oss.py` / `tests/services/metadata/test_bootstrap.py` | 单测 | Create |

---

## Task 1: `fetch_oss_tars` —— 从 OSS 前缀下载 *.tar 到本地

**Files:**
- Create: `pipelines/data_prep/oss_fetch.py`
- Test: `tests/pipelines/test_oss_fetch.py`

- [ ] **Step 1: 写失败测试(用假 s3 client,只验列+下载逻辑)**

```python
# tests/pipelines/test_oss_fetch.py
from pathlib import Path
from pipelines.data_prep.oss_fetch import fetch_oss_tars


class _FakeS3:
    """最小假 boto3 s3:list_objects_v2 + download_file。"""
    def __init__(self, keys):
        self._keys = keys
        self.downloaded = []

    def get_paginator(self, op):
        keys = self._keys
        class _P:
            def paginate(self, Bucket, Prefix):
                yield {"Contents": [{"Key": k} for k in keys if k.startswith(Prefix)]}
        return _P()

    def download_file(self, Bucket, Key, Filename):
        self.downloaded.append((Key, Filename))
        Path(Filename).write_bytes(b"fake-tar")


def test_fetch_only_tars_under_prefix(tmp_path):
    s3 = _FakeS3(["e-0001/g-0001/raw/coco/a.tar", "e-0001/g-0001/raw/coco/b.tar",
                  "e-0001/g-0001/raw/coco/notes.txt", "e-0001/g-0002/raw/x/c.tar"])
    n = fetch_oss_tars(s3, bucket="lite-ai", prefix="e-0001/g-0001/raw/coco/", dest_dir=str(tmp_path))
    got = sorted(p.name for p in tmp_path.glob("*.tar"))
    assert got == ["a.tar", "b.tar"]      # 只下该前缀下的 .tar,跳过 .txt 与别组
    assert n == 2


def test_fetch_zero_tars_returns_zero(tmp_path):
    s3 = _FakeS3(["e-0001/g-0001/raw/coco/readme.md"])
    assert fetch_oss_tars(s3, bucket="lite-ai", prefix="e-0001/g-0001/raw/coco/", dest_dir=str(tmp_path)) == 0
```

- [ ] **Step 2: 运行,确认失败**

Run: `uv run pytest tests/pipelines/test_oss_fetch.py -q`
Expected: FAIL（`ModuleNotFoundError: pipelines.data_prep.oss_fetch`）

- [ ] **Step 3: 实现 `pipelines/data_prep/oss_fetch.py`**

```python
# pipelines/data_prep/oss_fetch.py
"""从 OSS 前缀拉 webdataset *.tar 到本地(S2a:raw→prepare 的取数步)。
boto3 client 复用 libs/audit/oss_audit.py:oss_boto3_config(按 endpoint 自适配 addressing)。"""
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
    """下载 bucket/prefix 下所有 *.tar 到 dest_dir(扁平,用对象名末段)。返回个数。"""
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    n = 0
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if not key.endswith(".tar"):
                continue
            s3.download_file(bucket, key, str(dest / os.path.basename(key)))
            n += 1
    return n
```

- [ ] **Step 4: 运行,确认通过**

Run: `uv run pytest tests/pipelines/test_oss_fetch.py -q`
Expected: PASS（2 passed）

- [ ] **Step 5: Commit**

```bash
git add pipelines/data_prep/oss_fetch.py tests/pipelines/test_oss_fetch.py
git commit -m "feat(pipeline): fetch_oss_tars —— 从 OSS 前缀拉 webdataset tar 到本地(S2a 取数步)"
```

---

## Task 2: `run_prepare` 支持 OSS 源(tar_dir 缺省 → OSS raw 前缀)

**Files:**
- Modify: `pipelines/data_prep/runner.py`(`run_prepare`)
- Test: `tests/pipelines/test_runner_oss.py`

- [ ] **Step 1: 写失败测试(tar_dir 缺省 → 用 DatasetPaths.raw_prefix + 注入的 fetch seam)**

```python
# tests/pipelines/test_runner_oss.py
from libs.identity.context import Context, Membership
from libs.identity.ids import EnterpriseId, GroupId
from pipelines.data_prep.runner import run_prepare, PrepareRequest
from libs.audit.audit import AuditWriter, NullAuditSink   # 若路径不同,执行时按实际 import 改


def _ctx():
    return Context(user="u-alice", memberships=[Membership(EnterpriseId("e-0001"), GroupId("g-0001"), "member")])


def test_tar_dir_omitted_uses_oss_raw_prefix(tmp_path, monkeypatch):
    seen = {}
    # 注入 fetch_fn seam:断言它收到的是服务端拼出的 OSS raw 前缀(身份钉死)
    def fake_fetch(s3, *, bucket, prefix, dest_dir):
        seen["bucket"] = bucket; seen["prefix"] = prefix
        from pathlib import Path; Path(dest_dir).mkdir(parents=True, exist_ok=True)
        return 1
    def fake_convert(tar_dir, out_dir):
        from pathlib import Path; Path(out_dir).mkdir(parents=True, exist_ok=True)
        (Path(out_dir) / "data.jsonl").write_text('{"text":"x","images":[]}\n'); return 1
    def fake_dj(recipe, log): 
        from pathlib import Path; p = Path(recipe).parent / "out"; p.mkdir(parents=True, exist_ok=True)
        (p / "cleaned.jsonl").write_text('{"text":"x"}\n'); return 0
    def fake_lance(jsonl, uri, opts, endpoint): return 1

    req = PrepareRequest(tar_dir=None, work_dir=str(tmp_path), bucket="lite-ai",
                         enterprise_id="e-0001", group_id="g-0001", dataset="coco",
                         oss_endpoint="http://localhost:9000", access_key="minio",
                         secret_key="minio123", session_token=None, region="us-east-1", process=None)
    out = run_prepare(_ctx(), req, AuditWriter(NullAuditSink()),
                      convert_fn=fake_convert, dj_fn=fake_dj, lance_fn=fake_lance, fetch_fn=fake_fetch)
    assert seen["bucket"] == "lite-ai"
    assert seen["prefix"] == "e-0001/g-0001/raw/coco/"     # 服务端钉死(身份),非客户端路径
    assert out["lance_uri"].endswith("processed/coco.lance")
```

(注:`AuditWriter`/sink 的真实 import 路径以现有 `worker.py:_audit_writer` 为准;实现时对齐。`fetch_fn` 是新增 seam,默认 `fetch_oss_tars`。)

- [ ] **Step 2: 运行,确认失败**

Run: `uv run pytest tests/pipelines/test_runner_oss.py -q`
Expected: FAIL（`run_prepare() got unexpected keyword 'fetch_fn'` 或 tar_dir=None 时 convert 收到 None）

- [ ] **Step 3: 改 `run_prepare`(加 fetch_fn seam + tar_dir 缺省走 OSS)**

在 `pipelines/data_prep/runner.py` 顶部 import 加:
```python
from pipelines.data_prep.oss_fetch import fetch_oss_tars, build_s3
```
把 `run_prepare` 签名加 `fetch_fn=fetch_oss_tars`;在 `paths = DatasetPaths(...)` 之后、`n_in = convert_fn(...)` 之前,插入"tar_dir 缺省 → 从 OSS 取"逻辑:
```python
    src_dir = req.tar_dir
    if not src_dir:                                  # 缺省:从本组 OSS raw/{dataset}/ 取(身份钉死,ADR-020 范式)
        src_dir = str(Path(req.work_dir) / "tars")
        s3 = build_s3(req.oss_endpoint, req.access_key, req.secret_key, req.session_token, req.region)
        n_tar = fetch_fn(s3, bucket=req.bucket, prefix=paths.raw_prefix, dest_dir=src_dir)
        if n_tar == 0:
            raise RuntimeError(f"no .tar under oss raw prefix {paths.raw_prefix}")
    n_in = convert_fn(src_dir, str(jsonl_dir))
```
(把原 `n_in = convert_fn(req.tar_dir, ...)` 替成上面的 `convert_fn(src_dir, ...)`。`PrepareRequest.tar_dir` 改为可选 `str | None`,默认 None。)

- [ ] **Step 4: 运行,确认通过 + 旧测试不破**

Run: `uv run pytest tests/pipelines/ -q`
Expected: PASS（含原有 prepare 测试:tar_dir 给定时仍走本地,行为不变)

- [ ] **Step 5: Commit**

```bash
git add pipelines/data_prep/runner.py tests/pipelines/test_runner_oss.py
git commit -m "feat(pipeline): run_prepare 支持 OSS 源(tar_dir 缺省→raw 前缀服务端钉死+fetch)"
```

---

## Task 3: 契约 + 端点 + JobSpec 让 tar_dir 可选

**Files:**
- Modify: `contracts/openapi/data-pipeline.yaml:62`(required)
- Modify: `services/data_pipeline_service/app.py`(prepare)
- Modify: `services/data_pipeline_service/worker.py` / JobSpec(tar_dir 可选)

- [ ] **Step 1: 改契约 —— tar_dir 移出 required**

`contracts/openapi/data-pipeline.yaml` 的 `PrepareJobRequest`:
- 第 62 行 `required: [dataset, group_id, tar_dir]` → `required: [dataset, group_id]`
- 第 66 行 tar_dir 注释更新:`# 可选:给定=本地 ops 路径(S1);缺省=从本组 OSS raw/{dataset}/ 取(S2a)`

- [ ] **Step 2: `make gen` 重生成类型 + 确认编译**

Run: `make gen && uv run python -c "from libs.contracts_gen.data_pipeline_models import PrepareJobRequest; print(PrepareJobRequest.model_fields['tar_dir'])"`
Expected: tar_dir 变为可选(无报错)。

- [ ] **Step 3: 端点 + JobSpec 透传可选 tar_dir**

`services/data_pipeline_service/app.py` prepare:`JobSpec(..., tar_dir=body.tar_dir, ...)` —— `body.tar_dir` 现可为 None,直传即可(JobSpec.tar_dir 类型若是 str,改 `str | None`)。
确认 `worker.py` 构造 `PrepareRequest(tar_dir=spec.tar_dir, ...)` 在 spec.tar_dir=None 时透传。`JobSpec`(在 runner/store 定义处)的 `tar_dir` 字段改 `str | None = None`。

- [ ] **Step 4: 加端点测试(tar_dir 省略 → 202,spec.tar_dir 为 None)**

在 data-pipeline 服务测试里(`tests/services/data_pipeline/`)加:
```python
def test_prepare_without_tar_dir_accepts(client_with_test_claims):
    r = client_with_test_claims.post("/v1/data/prepare",
        json={"dataset": "coco", "group_id": "g-0001"})   # 无 tar_dir
    assert r.status_code == 202
```
(`client_with_test_claims`:沿用该目录现有起带 LITEAI_ALLOW_TEST_CLAIMS 的测试夹具;按现有测试样式接 fixture。)

- [ ] **Step 5: 运行 + Commit**

Run: `uv run pytest tests/services/data_pipeline/ -q` → PASS
```bash
git add contracts/openapi/data-pipeline.yaml libs/contracts_gen/data_pipeline_models.py services/data_pipeline_service/ tests/services/data_pipeline/
git commit -m "feat(contract): PrepareJobRequest.tar_dir 改可选(缺省走 OSS raw)"
```

---

## Task 4: metadata 注册自动建 catalog/schema + 列表 404→空

**Files:**
- Modify: `services/metadata_service/app.py`(register、list_ds)
- Test: `tests/services/metadata/test_bootstrap.py`

- [ ] **Step 1: 写失败测试(空 catalog 时 list 返空、register 先 ensure)**

```python
# tests/services/metadata/test_bootstrap.py —— 用假 Gravitino client(沿用现有 test_gravitino_client 的 FakeHttp 模式)
# 断言:① list_ds 在 list_filesets 抛 404 时返回 {"datasets": []} 而非 500
#       ② register 调用前会 ensure_catalog + ensure_schema(幂等)
# 具体夹具按 tests/services/metadata/ 现有样式装(注入 GravitinoClient 假实现 / monkeypatch ensure_*)。
```
(实现者:照 `tests/services/metadata/test_gravitino_client.py` 的假 client 模式;两条断言:list 404→空、register 触发 ensure_catalog/ensure_schema。)

- [ ] **Step 2: 运行,确认失败**

Run: `uv run pytest tests/services/metadata/test_bootstrap.py -q`
Expected: FAIL

- [ ] **Step 3: list_ds 容错 404 → 空**

`services/metadata_service/app.py` 的 `list_ds`,把 `for name in gravitino.list_filesets(...)` 包起来:
```python
        try:
            names = gravitino.list_filesets(ml, catalog, schema)
        except GravitinoError as e:
            if getattr(e, "status", None) == 404:    # catalog/schema 尚未建(空租户)→ 空列表
                return {"datasets": []}
            raise
        for name in names:
            ...
```

- [ ] **Step 4: register 先 ensure_catalog/ensure_schema(幂等)**

register handler 在 `create_fileset(...)` 之前插入(读 OSS 配置以建 fileset catalog;dev 值从 env):
```python
        gravitino.ensure_metalake(ml)
        gravitino.ensure_catalog(ml, catalog, bucket=os.environ["DATA_BUCKET"],
                                 s3_endpoint=os.environ["OSS_ENDPOINT"],
                                 access_key=os.environ["OSS_ACCESS_KEY"],
                                 secret_key=os.environ["OSS_SECRET_KEY"])
        gravitino.ensure_schema(ml, catalog, schema)
```
(`ensure_*` 已存在于 `services/metadata_service/gravitino.py`,幂等容忍 409。metadata 服务启动需补 OSS env —— 见 Task 6 runbook 起服务时注入;以及把这些 key 纳入 `libs/config` 的 metadata 子集,见 Step 5。)

- [ ] **Step 5: 把 OSS env 纳入 metadata 服务(env-config 单一源)**

metadata 现在要读 OSS 配置 → 在 `libs/config/__init__.py:SERVICE_ENV_KEYS["metadata"]` 加 `OSS_ENDPOINT/OSS_ACCESS_KEY/OSS_SECRET_KEY/DATA_BUCKET`(值来自 configs/local.yaml,已有)。更新 `tests/config/test_loader.py` 的 metadata 基线键集断言。

- [ ] **Step 6: 运行 + Commit**

Run: `uv run pytest tests/services/metadata/ tests/config/ -q` → PASS
```bash
git add services/metadata_service/app.py libs/config/__init__.py tests/services/metadata/test_bootstrap.py tests/config/test_loader.py
git commit -m "feat(metadata): 注册自动 ensure catalog/schema + 列表 404→空(空租户可跑)"
```

---

## Task 5: 前端 CreateJob —— 源改"已上传 raw 数据集"下拉

**Files:**
- Modify: `frontend/src/pages/CreateJob.tsx`
- Modify: `frontend/src/api/jobs.ts`(若需 listRaw)
- Test: `frontend/src/pages/CreateJob.test.tsx`(Create)

- [ ] **Step 1: jobs.ts/数据源:复用 raw 列表**

`frontend/src/api/upload.ts` 或新增:`listRaw(): Promise<RawDatasetList>` = `api.get('/v1/data/raw')`(若已有则复用)。Row 需要 `name` 与 `status`(只列 `ready`)。

- [ ] **Step 2: 写失败测试(下拉渲染 ready 的 raw;选中后提交 dataset=该名、无 tar_dir)**

```tsx
// frontend/src/pages/CreateJob.test.tsx
import { it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { CreateJob } from './CreateJob'

afterEach(() => vi.unstubAllGlobals())

it('源下拉列出 ready 的 raw 数据集,提交用其名且不带 tar_dir', async () => {
  const calls: any[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: any) => {
    if (String(url).includes('/v1/data/raw')) return { ok: true, status: 200, json: async () => ({ raws: [{ name: 'coco', status: 'ready' }, { name: 'pending-x', status: 'pending' }] }) }
    calls.push(JSON.parse(init.body)); return { ok: true, status: 200, json: async () => ({ id: 'job-1', terminal: false }) }
  }))
  render(<MemoryRouter><CreateJob /></MemoryRouter>)
  await waitFor(() => screen.getByRole('option', { name: 'coco' }))
  fireEvent.change(screen.getByLabelText(/源/), { target: { value: 'coco' } })
  fireEvent.change(screen.getByLabelText(/用户组/), { target: { value: 'g-0001' } })
  fireEvent.click(screen.getByText('提交作业'))
  await waitFor(() => expect(calls.length).toBe(1))
  expect(calls[0]).toMatchObject({ dataset: 'coco', group_id: 'g-0001' })
  expect(calls[0].tar_dir).toBeUndefined()    // 从 OSS 取,不传路径
})
```
(`RawDatasetList` 的实际字段名以契约为准——执行时核 `contracts/openapi/data-pipeline.yaml` 的 RawDatasetList(可能是 `raws` 或 `datasets`);测试与实现对齐真实字段。)

- [ ] **Step 3: 改 CreateJob.tsx**

把"源数据位置(tar_dir)文本框"换成 **select 下拉**:挂载时 `listRaw()` → 过滤 `status==='ready'` → `<option>`;state `source`(选中的 raw 数据集名)。提交时 `createJob({ dataset: source, group_id, np?, process? })`(**不传 tar_dir**)。`canSubmit` 改判 `source`。文案改"源:已上传的原始数据集(从 OSS 直接读)"。移除 `tarDir` state 与那段过渡说明。

- [ ] **Step 4: 运行前端测试 + 构建**

Run: `cd frontend && npx vitest run src/pages/CreateJob.test.tsx && npm run build`
Expected: PASS + build 成功。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/CreateJob.tsx frontend/src/api/jobs.ts frontend/src/api/upload.ts frontend/src/pages/CreateJob.test.tsx
git commit -m "feat(frontend): CreateJob 源改'已上传 raw 数据集'下拉(从 OSS 跑,不手填路径)"
```

---

## Task 6: e2e 夹具 + owner-readable 验收 runbook

**Files:**
- Create: `scripts/make_coco_smoke_tar.py`
- Modify: 本计划文件(嵌 runbook)

- [ ] **Step 1: coco webdataset tar 夹具脚本**

```python
# scripts/make_coco_smoke_tar.py —— 取 coco-30-val ~64 条,打包成 webdataset tar({key}.jpg+{key}.txt)
import io, os, tarfile
from datasets import load_dataset

N = int(os.getenv("N", "64"))
out_dir = os.getenv("OUT", "./.smoke")
os.makedirs(out_dir, exist_ok=True)
ds = load_dataset("sayakpaul/coco-30-val-2014", split="train", streaming=True)
tar_path = os.path.join(out_dir, "coco-smoke.tar")
with tarfile.open(tar_path, "w") as tar:
    for i, row in zip(range(N), ds):
        key = f"{i:05d}"
        img = row.get("image") or row.get("Image")
        cap = (row.get("caption") or row.get("Caption") or "").strip()
        if img is None or not cap:
            continue
        buf = io.BytesIO(); img.convert("RGB").save(buf, format="JPEG"); b = buf.getvalue()
        ti = tarfile.TarInfo(f"{key}.jpg"); ti.size = len(b); tar.addfile(ti, io.BytesIO(b))
        cb = cap.encode("utf-8"); tt = tarfile.TarInfo(f"{key}.txt"); tt.size = len(cb); tar.addfile(tt, io.BytesIO(cb))
print("wrote", tar_path)
```
Run(验证夹具能产出):`uv run python scripts/make_coco_smoke_tar.py && tar tf ./.smoke/coco-smoke.tar | head`
Expected: 列出 `00000.jpg 00000.txt …`。

- [ ] **Step 2: Commit 脚本**

```bash
git add scripts/make_coco_smoke_tar.py
git commit -m "test(smoke): coco-30-val→webdataset tar 夹具脚本"
```

- [ ] **Step 3: 全绿门禁**

Run: `make gen && make lint && uv run pytest -q` → 全 PASS;`cd frontend && npx vitest run` → PASS。

- [ ] **Step 4: 把下方 runbook 写进本文件并提交**

```bash
git add docs/superpowers/plans/2026-06-23-oss-raw-to-prepare.md
git commit -m "docs(plan): OSS→管线 手动验收 runbook"
```

---

## 手动验收 Runbook(owner 逐步跑,白话)

> 在仓库根目录、终端逐条复制运行。前置:Docker 在跑;已 `make dj-setup`。

- [ ] **1. 起本地全栈**
  - 跑:`make up`(等约 40 秒)
  - 应看到:几行服务起来 + `入口:gateway http://localhost:8090`。

- [ ] **2. 造数据(coco 一小片打包成 tar)**
  - 跑:`uv run python scripts/make_coco_smoke_tar.py`
  - 应看到:`wrote ./.smoke/coco-smoke.tar`。

- [ ] **3. 把这份 tar 当"原始数据集 coco"上传到对象存储**
  - 跑:`docker run --rm --network dev_default -v "$PWD/.smoke:/d" --entrypoint sh minio/mc -c "mc alias set x http://minio:9000 minio minio123 && mc cp /d/coco-smoke.tar x/lite-ai/e-0001/g-0001/raw/coco/coco-smoke.tar && mc ls x/lite-ai/e-0001/g-0001/raw/coco/"`
  - 应看到:列出 `coco-smoke.tar`(它进了"我的企业/我的组/原始/coco"下)。
  - (这一步等价于"控制台上传";控制台 UI 上传那条线起同样效果。)

- [ ] **4. 浏览器里建作业(从 OSS 跑管线)**
  - 打开 `http://localhost:8090` → 登录 → 左侧「创建作业」。
  - 「源」下拉里选 **coco**;用户组填 `g-0001`;点「提交作业」。
  - 应看到:提示"作业已提交",跳到「数据管线」。

- [ ] **5. 等作业跑完**
  - 在「数据管线」页看那条作业,状态从 处理中 → **成功**(几十秒,DJ 在跑)。
  - 成功 = 它**真的从 OSS 读了你上传的 tar、跑完了清洗、把结果写回了对象存储**。

- [ ] **6. 注册到数据目录**
  - 作业成功后,按页面提示把产物注册进「数据目录」(或在数据集页点注册)。
  - 应看到:数据集 / 数据目录页里出现 **coco**(已处理),不再报错。

- [ ] **7.(可选)看结果落在哪**
  - 跑:`docker run --rm --network dev_default --entrypoint sh minio/mc -c "mc alias set x http://minio:9000 minio minio123 && mc ls -r x/lite-ai/e-0001/g-0001/processed/"`
  - 应看到:`coco.lance` 相关文件 = 清洗结果已落对象存储。

> 任何一步对不上就把输出贴给我。全过 = "下载→上传→从 OSS 跑管线→注册" 全链路通。

---

## Self-Review
- **OSS 源打通**(核心)→ Task 1(fetch)+ Task 2(run_prepare 缺省走 OSS,前缀身份钉死)+ Task 3(契约可选)。✅
- **隔离**:前缀只来自 `DatasetPaths(ctx 的 eid, group, dataset)`,测试断言前缀=`e-0001/g-0001/raw/coco/`,不收客户端路径。✅
- **全链路缺口**:注册自动建 catalog/schema + 列表 404→空 → Task 4。✅
- **前端**:源改下拉、不传 tar_dir → Task 5。✅
- **验收**:coco 夹具 + owner runbook 跑完整链路 → Task 6。✅
- **env-config 单一源**:metadata 新增 OSS env 纳入 SERVICE_ENV_KEYS + 基线测试同步 → Task 4 Step 5。✅
- Placeholder 扫描:契约 RawDatasetList 字段名、AuditWriter import 路径标注"执行时按实际对齐"(非缺口,是已知需现场核的点)。
- 类型一致:`fetch_oss_tars`/`build_s3`/`run_prepare(fetch_fn=)`/`PrepareRequest.tar_dir: str|None`/`JobSpec.tar_dir` 跨任务一致。✅
