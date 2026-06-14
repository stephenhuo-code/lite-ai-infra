# S1 Plan 2:pipelines/data_prep(一行命令:图文 tar → 清洗 → Lance on OSS)实现计划

> **✅ 状态(2026-06-14 补勾对齐):全部任务已完成并合并,S1 出口① 已验收。** 云上端到端真跑产出 `rows_in=15138`(CC3M 1.39GB),清洗后 Lance 数据集已落 OSS 企业/组隔离路径,入口经 `can()` + 审计。代码见 `pipelines/data_prep/`(commit 区间 `e1554da`→`0efcc09`);出口① 状态见主 spec §5.3 与 `docs/adr/ADR-014-...`。下方 checkbox 为事后补勾(执行期未实时回写,违反 ADR-017,已知)。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付 S1 出口①的生产形态:一行命令把 webdataset tar 经 Data-Juicer+Ray 清洗后写成 OSS 上的 Lance 数据集(企业/组隔离路径),入口经 `can()` + 审计。

**Architecture:** 新增 `pipelines` 层(import-linter:`services → pipelines → libs`)。纯逻辑(路径/recipe/转换)与副作用(DJ 子进程、Lance 写)分离;DJ 经 subprocess 调外部 venv(spike 教训:Ray 禁瞬态 uv 环境);Lance 写吃 Spike 1 的三条约束(virtual-hosted+bucket-in-endpoint、checksum when_required、OSS 用 commit_lock)。授权走唯一 `can()` 出入口,审计 best-effort(宪法 §2.4/§6)。

**Tech Stack:** Python 3.12 + uv(主 venv 只加 `pylance`;DJ/Ray 留在独立 venv)、Data-Juicer(subprocess)、Lance、boto3、pytest 两层(unit / integration-MinIO)。

**Spike 输入(已实证):** np=vCPU+1 起步;内存 = 基线 3GB+50MB/np(轻算子);OSS 写必须 `commit_lock`(单写者 no-op 安全);内网 endpoint。

---

### Task 1:`pipelines` 层 + import-linter 分层扩展

**Files:**
- 创建:`pipelines/__init__.py`、`pipelines/data_prep/__init__.py`
- 修改:`.importlinter`(三层契约)、`pyproject.toml`(dev 依赖加 `pylance>=0.18`)

- [x] **步骤 1:建包 + 改 `.importlinter`**

```ini
[importlinter]
root_packages = libs, services, pipelines

[importlinter:contract:layers]
name = layering
type = layers
layers =
    services
    pipelines
    libs
```

- [x] **步骤 2:`pyproject.toml` 的 `[project.optional-dependencies].dev` 追加 `"pylance>=0.18"`,跑 `uv lock && make sync`**

- [x] **步骤 3:验证** —— `uv run lint-imports` 期望 `1 kept, 0 broken`;`uv run pytest -q` 全绿(无回归)。

- [x] **步骤 4:提交** `git commit -m "feat(pipelines): add pipelines layer (services→pipelines→libs)"`

---

### Task 2:隔离路径构造 `paths.py`(TDD,纯逻辑)

**Files:**
- 创建:`pipelines/data_prep/paths.py`、`tests/pipelines/__init__.py`、`tests/pipelines/test_paths.py`

- [x] **步骤 1:写失败测试**

```python
# tests/pipelines/test_paths.py
import pytest
from libs.identity.ids import EnterpriseId, GroupId
from pipelines.data_prep.paths import DatasetPaths

E, G = EnterpriseId("e-0001"), GroupId("g-0001")

def test_paths_encode_enterprise_and_group():
    p = DatasetPaths(bucket="b", enterprise_id=E, group_id=G, dataset="cc3m")
    assert p.raw_prefix == "e-0001/g-0001/raw/cc3m/"
    assert p.processed_uri == "s3://b/e-0001/g-0001/processed/cc3m.lance"
    assert p.cleaned_prefix == "e-0001/g-0001/cleaned/cc3m/"

def test_dataset_name_validated():
    with pytest.raises(ValueError):
        DatasetPaths(bucket="b", enterprise_id=E, group_id=G, dataset="Bad Name!")
    with pytest.raises(ValueError):
        DatasetPaths(bucket="b", enterprise_id=E, group_id=G, dataset="a/../b")
```

- [x] **步骤 2:跑红** `uv run pytest tests/pipelines/test_paths.py -q` → ModuleNotFoundError

- [x] **步骤 3:最小实现**

```python
# pipelines/data_prep/paths.py
from __future__ import annotations
import re
from dataclasses import dataclass
from libs.identity.ids import EnterpriseId, GroupId

_RE_DATASET = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

@dataclass(frozen=True)
class DatasetPaths:
    """资源命名只含不透明 ID(宪法 §1.4):oss://<bucket>/<eid>/<gid>/{raw,cleaned,processed}/…"""
    bucket: str
    enterprise_id: EnterpriseId
    group_id: GroupId
    dataset: str

    def __post_init__(self):
        if not _RE_DATASET.match(self.dataset):
            raise ValueError(f"invalid dataset name: {self.dataset!r}")

    @property
    def _base(self) -> str:
        return f"{self.enterprise_id}/{self.group_id}"

    @property
    def raw_prefix(self) -> str:
        return f"{self._base}/raw/{self.dataset}/"

    @property
    def cleaned_prefix(self) -> str:
        return f"{self._base}/cleaned/{self.dataset}/"

    @property
    def processed_uri(self) -> str:
        return f"s3://{self.bucket}/{self._base}/processed/{self.dataset}.lance"
```

- [x] **步骤 4:跑绿** → 2 passed;**步骤 5:提交** `feat(pipelines): isolated dataset paths (opaque IDs only)`

---

### Task 3:DJ recipe 生成 `recipe.py`(TDD,纯逻辑)

**Files:**
- 创建:`pipelines/data_prep/recipe.py`、`tests/pipelines/test_recipe.py`

- [x] **步骤 1:写失败测试**

```python
# tests/pipelines/test_recipe.py
import yaml
from pipelines.data_prep.recipe import build_recipe

def test_recipe_defaults_from_spike():
    r = yaml.safe_load(build_recipe(input_jsonl="/d/in.jsonl", out_dir="/d/out", np=3))
    assert r["executor_type"] == "ray" and r["ray_address"] == "auto"
    assert r["np"] == 3
    assert r["dataset_path"] == "/d/in.jsonl"
    assert r["export_path"] == "/d/out/cleaned.jsonl"
    ops = [list(o)[0] for o in r["process"]]
    assert ops == ["text_length_filter", "image_shape_filter", "image_aspect_ratio_filter"]

def test_recipe_custom_ops_override():
    r = yaml.safe_load(build_recipe("/i", "/o", np=2, process=[{"text_length_filter": {"min_len": 1}}]))
    assert r["process"] == [{"text_length_filter": {"min_len": 1}}]
```

- [x] **步骤 2:跑红**(需 dev 依赖 `pyyaml`;若缺:dev 加 `"pyyaml>=6"` 并 `uv lock && make sync`)

- [x] **步骤 3:最小实现**

```python
# pipelines/data_prep/recipe.py
from __future__ import annotations
import yaml

# Spike 2 实证的轻算子默认集(spikes/datajuicer_ray/RESULTS-aliyun.md)
_DEFAULT_PROCESS = [
    {"text_length_filter": {"min_len": 3, "max_len": 2000}},
    {"image_shape_filter": {"min_width": 8, "min_height": 8}},
    {"image_aspect_ratio_filter": {"min_ratio": 0.2, "max_ratio": 5.0}},
]

def build_recipe(input_jsonl: str, out_dir: str, np: int,
                 process: list[dict] | None = None, project: str = "data-prep") -> str:
    """生成 Data-Juicer RayExecutor recipe(np 取 vCPU+1 起步,Spike 2 结论)。"""
    cfg = {
        "project_name": project,
        "dataset_path": input_jsonl,
        "export_path": f"{out_dir}/cleaned.jsonl",
        "executor_type": "ray",
        "ray_address": "auto",
        "np": np,
        "text_keys": "text",
        "image_key": "images",
        "process": process if process is not None else _DEFAULT_PROCESS,
    }
    return yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False)
```

- [x] **步骤 4:跑绿** → 2 passed;**步骤 5:提交** `feat(pipelines): DJ recipe builder with spike-validated defaults`

---

### Task 4:tar→jsonl 转换迁入生产层(TDD;spike 代码不被生产 import)

**Files:**
- 创建:`pipelines/data_prep/ingest.py`、`tests/pipelines/test_ingest.py`

- [x] **步骤 1:写失败测试**(用 tmp_path 构造 2 配对 + 1 孤图的小 tar;断言 2 行、孤图丢弃、jsonl 含绝对路径)

```python
# tests/pipelines/test_ingest.py
import io, json, tarfile
from pipelines.data_prep.ingest import wds_to_jsonl

_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de"
    "0000000c4944415408d763f8cfc0000003010100c9fe92ef0000000049454e44ae426082")

def _mk_tar(p):
    with tarfile.open(p, "w") as tf:
        for key, txt in [("00001", "a cat"), ("00002", "blue sky")]:
            ti = tarfile.TarInfo(f"{key}.jpg"); ti.size = len(_PNG); tf.addfile(ti, io.BytesIO(_PNG))
            t = txt.encode(); ti2 = tarfile.TarInfo(f"{key}.txt"); ti2.size = len(t); tf.addfile(ti2, io.BytesIO(t))
        ti = tarfile.TarInfo("orphan.jpg"); ti.size = len(_PNG); tf.addfile(ti, io.BytesIO(_PNG))

def test_wds_to_jsonl_pairs_and_drops_orphans(tmp_path):
    tar_dir = tmp_path / "tars"; tar_dir.mkdir(); _mk_tar(tar_dir / "s-000.tar")
    out = tmp_path / "out"
    n = wds_to_jsonl(str(tar_dir), str(out))
    assert n == 2
    rows = [json.loads(l) for l in open(out / "data.jsonl")]
    assert rows[0]["text"] == "a cat"
    assert rows[0]["images"][0].startswith("/")
```

- [x] **步骤 2:跑红**;**步骤 3:实现** —— 把 `spikes/datajuicer_ray/wds_to_jsonl.py` 的 `convert()` 迁为 `pipelines/data_prep/ingest.py::wds_to_jsonl(tar_dir, out_dir) -> int`(逻辑同源:配对 .jpg/.jpeg/.png/.webp 与 .txt、孤图丢弃;函数化、无 `__main__`)。spike 文件保留但头部加注释"生产版在 pipelines/data_prep/ingest.py"。

- [x] **步骤 4:跑绿**;**步骤 5:提交** `feat(pipelines): productionize wds->jsonl ingest`

---

### Task 5:Lance 写入 `lance_writer.py`(TDD:单测纯逻辑 + 集成真 MinIO)

**Files:**
- 创建:`pipelines/data_prep/lance_writer.py`、`tests/pipelines/test_lance_writer.py`、`tests/integration/test_lance_minio.py`

- [x] **步骤 1:写失败单测**(storage options 构造——Spike 1 三条约束的固化)

```python
# tests/pipelines/test_lance_writer.py
from pipelines.data_prep.lance_writer import lance_storage_options

def test_storage_options_minio_path_style():
    o = lance_storage_options("http://localhost:9000", "bkt", "ak", "sk")
    assert o["endpoint"] == "http://localhost:9000"
    assert o["virtual_hosted_style_request"] == "false"
    assert o["allow_http"] == "true"
    assert "conditional_put" not in o          # MinIO 走默认条件写

def test_storage_options_oss_virtual_bucket_in_endpoint():
    o = lance_storage_options("https://oss-cn-hangzhou-internal.aliyuncs.com", "bkt", "ak", "sk",
                              session_token="tok")
    assert o["endpoint"] == "https://bkt.oss-cn-hangzhou-internal.aliyuncs.com"  # 约束3
    assert o["virtual_hosted_style_request"] == "true"                            # 约束1
    assert o["session_token"] == "tok"

def test_oss_needs_commit_lock():
    from pipelines.data_prep.lance_writer import needs_commit_lock
    assert needs_commit_lock("https://oss-cn-hangzhou.aliyuncs.com") is True      # 约束:If-None-Match
    assert needs_commit_lock("http://localhost:9000") is False
```

- [x] **步骤 2:跑红**;**步骤 3:实现**

```python
# pipelines/data_prep/lance_writer.py
from __future__ import annotations
import contextlib, glob, json
import lance
import pyarrow as pa

def _is_oss(endpoint: str) -> bool:
    return "aliyuncs.com" in endpoint

def needs_commit_lock(endpoint: str) -> bool:
    """OSS 无 If-None-Match 条件写 → Lance manifest 提交需外部 commit_lock
    (Spike 1 实测;单写者 no-op 锁安全,多写者真锁属 S2a)。"""
    return _is_oss(endpoint)

def lance_storage_options(endpoint: str, bucket: str, access_key: str, secret_key: str,
                          session_token: str | None = None, region: str = "cn-hangzhou") -> dict:
    """Spike 1 三条约束固化:virtual-hosted(OSS)/path(MinIO);
    virtual 模式 bucket 必须拼进 endpoint;http 才 allow_http。"""
    virtual = _is_oss(endpoint)
    scheme, host = endpoint.split("://", 1)
    opts = {
        "access_key_id": access_key,
        "secret_access_key": secret_key,
        "endpoint": f"{scheme}://{bucket}.{host}" if virtual else endpoint,
        "region": region,
        "allow_http": "true" if scheme == "http" else "false",
        "virtual_hosted_style_request": "true" if virtual else "false",
    }
    if session_token:
        opts["session_token"] = session_token
    return opts

@contextlib.contextmanager
def _noop_lock(_version):
    yield

def write_cleaned_to_lance(cleaned_dir: str, uri: str, storage_options: dict,
                           endpoint: str) -> int:
    """DJ 输出(目录式 jsonl part 文件)→ Lance dataset。返回行数。"""
    rows = []
    for part in sorted(glob.glob(f"{cleaned_dir}/*.json*")):
        with open(part) as fh:
            rows.extend(json.loads(l) for l in fh if l.strip())
    if not rows:
        raise ValueError(f"no rows found under {cleaned_dir}")
    tbl = pa.table({
        "text": pa.array([r["text"] for r in rows]),
        "image_path": pa.array([r["images"][0] if r.get("images") else "" for r in rows]),
    })
    kw = {"commit_lock": _noop_lock} if needs_commit_lock(endpoint) else {}
    lance.write_dataset(tbl, uri, storage_options=storage_options, mode="overwrite", **kw)
    return len(rows)
```

- [x] **步骤 4:跑绿(单测)**;**步骤 5:写集成测试(真 MinIO)**

```python
# tests/integration/test_lance_minio.py
import json, pytest
import lance
from pipelines.data_prep.lance_writer import lance_storage_options, write_cleaned_to_lance
pytestmark = pytest.mark.integration

def test_write_and_read_lance_on_minio(minio_s3, minio_bucket, tmp_path):
    d = tmp_path / "cleaned"; d.mkdir()
    (d / "part-0.jsonl").write_text("\n".join(
        json.dumps({"text": f"t{i}", "images": [f"/img/{i}.jpg"]}) for i in range(10)))
    ep = "http://localhost:9000"
    opts = lance_storage_options(ep, minio_bucket, "minio", "minio123", region="us-east-1")
    uri = f"s3://{minio_bucket}/e-0001/g-0001/processed/it.lance"
    assert write_cleaned_to_lance(str(d), uri, opts, ep) == 10
    ds = lance.dataset(uri, storage_options=opts)
    assert ds.count_rows() == 10
    assert ds.to_table(columns=["text"]).num_rows == 10
```

- [x] **步骤 6:`make dev-up` 后跑** `uv run pytest -q -m integration` → 全部集成绿(原 2 + 新 1)
- [x] **步骤 7:提交** `feat(pipelines): lance writer with spike-1 constraints baked in`

---

### Task 6:编排入口 `runner.py` —— can() → 转换 → DJ 子进程 → Lance → 审计(TDD)

**Files:**
- 创建:`pipelines/data_prep/runner.py`、`tests/pipelines/test_runner.py`

- [x] **步骤 1:写失败测试**(DJ 子进程与 Lance 写用 seam 注入 fake;授权/审计走真实现)

```python
# tests/pipelines/test_runner.py
import json, pytest
from libs.identity.context import parse_context
from libs.audit.oss_audit import AuditWriter
from pipelines.data_prep.runner import PrepareRequest, run_prepare

class MemoryAuditSink:
    def __init__(self): self.items = []
    def put(self, key, body): self.items.append((key, body))

def _req(tmp_path, **kw):
    d = tmp_path / "tars"; d.mkdir(exist_ok=True)
    return PrepareRequest(tar_dir=str(d), work_dir=str(tmp_path / "work"),
                          bucket="bkt", enterprise_id="e-0001", group_id="g-0001",
                          dataset="cc3m", np=3, oss_endpoint="http://localhost:9000",
                          access_key="ak", secret_key="sk", **kw)

def _ok_fakes(calls):
    return dict(
        convert_fn=lambda tar, out: calls.append(("convert", tar)) or 5,
        dj_fn=lambda recipe_path, log_path: calls.append(("dj", recipe_path)) or 0,
        lance_fn=lambda cleaned, uri, opts, ep: calls.append(("lance", uri)) or 5)

def test_denied_caller_gets_no_side_effects(tmp_path):
    sink = MemoryAuditSink(); calls = []
    ctx = parse_context("u-x", ["/e-0099/g-0001/members"])       # 跨企业
    with pytest.raises(PermissionError):
        run_prepare(ctx, _req(tmp_path), AuditWriter(sink), **_ok_fakes(calls))
    assert calls == []                                            # 无任何副作用
    assert len(sink.items) == 1                                   # deny 也审计
    assert json.loads(sink.items[0][1])["decision"] == "deny"

def test_happy_path_runs_stages_and_audits(tmp_path):
    sink = MemoryAuditSink(); calls = []
    ctx = parse_context("u-alice", ["/e-0001/g-0001/members"])
    out = run_prepare(ctx, _req(tmp_path), AuditWriter(sink), **_ok_fakes(calls))
    assert [c[0] for c in calls] == ["convert", "dj", "lance"]
    assert out["rows_written"] == 5
    assert out["lance_uri"] == "s3://bkt/e-0001/g-0001/processed/cc3m.lance"
    assert json.loads(sink.items[0][1])["decision"] == "allow"

def test_dj_failure_audited_and_raises(tmp_path):
    sink = MemoryAuditSink(); calls = []
    ctx = parse_context("u-alice", ["/e-0001/g-0001/members"])
    fakes = _ok_fakes(calls); fakes["dj_fn"] = lambda r, l: 1     # 非零退出
    with pytest.raises(RuntimeError):
        run_prepare(ctx, _req(tmp_path), AuditWriter(sink), **fakes)
    assert any(json.loads(b)["action"] == "data.prepare.failed" for _, b in sink.items)
```

- [x] **步骤 2:跑红**;**步骤 3:实现**

```python
# pipelines/data_prep/runner.py
from __future__ import annotations
import os, subprocess
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

from libs.identity.context import Context
from libs.identity.ids import EnterpriseId, GroupId
from libs.authz.engine import can
from libs.authz.types import Resource
from libs.audit.oss_audit import AuditWriter, AuditEvent
from pipelines.data_prep.paths import DatasetPaths
from pipelines.data_prep.recipe import build_recipe
from pipelines.data_prep.ingest import wds_to_jsonl
from pipelines.data_prep.lance_writer import lance_storage_options, write_cleaned_to_lance

@dataclass(frozen=True)
class PrepareRequest:
    tar_dir: str
    work_dir: str
    bucket: str
    enterprise_id: str
    group_id: str
    dataset: str
    np: int
    oss_endpoint: str
    access_key: str
    secret_key: str
    session_token: str | None = None
    region: str = "cn-hangzhou"

def _run_dj(recipe_path: str, log_path: str) -> int:
    """DJ 经外部 venv 子进程(spike 教训:Ray 禁瞬态 uv 环境)。DJ_BIN 指 dj-process。"""
    dj = os.getenv("DJ_BIN", "dj-process")
    with open(log_path, "w") as log:
        return subprocess.run([dj, "--config", recipe_path], stdout=log, stderr=log,
                              env={**os.environ, "HF_HUB_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1"},
                              ).returncode

def _audit(audit: AuditWriter, ctx: Context, req: PrepareRequest, action: str,
           decision: str, reason: str = "") -> None:
    audit.write(AuditEvent(
        ts=datetime.now(timezone.utc).isoformat(), enterprise_id=req.enterprise_id,
        group_id=req.group_id, actor_user=ctx.user,
        actor_role=ctx.role_in(EnterpriseId(req.enterprise_id), GroupId(req.group_id)) or "none",
        action=action, resource_uri=f"dataset/{req.dataset}", decision=decision,
        override=False, reason=reason, metadata={}))

def run_prepare(ctx: Context, req: PrepareRequest, audit: AuditWriter, *,
                convert_fn=wds_to_jsonl, dj_fn=_run_dj, lance_fn=write_cleaned_to_lance) -> dict:
    """一次数据准备:can() 唯一出入口 → 转换 → DJ(Ray)→ Lance on OSS → 审计。"""
    resource = Resource(kind="dataset", enterprise_id=EnterpriseId(req.enterprise_id),
                        group_id=GroupId(req.group_id))
    d = can(ctx, "data.prepare", resource)
    _audit(audit, ctx, req, "data.prepare", "allow" if d.allow else "deny", d.reason)
    if not d.allow:
        raise PermissionError(d.reason)

    paths = DatasetPaths(bucket=req.bucket, enterprise_id=EnterpriseId(req.enterprise_id),
                         group_id=GroupId(req.group_id), dataset=req.dataset)
    work = Path(req.work_dir); work.mkdir(parents=True, exist_ok=True)
    jsonl_dir, cleaned_dir = work / "in", work / "out"

    n_in = convert_fn(req.tar_dir, str(jsonl_dir))
    recipe_path = work / "recipe.yaml"
    recipe_path.write_text(build_recipe(str(jsonl_dir / "data.jsonl"), str(cleaned_dir), req.np))
    rc = dj_fn(str(recipe_path), str(work / "dj.log"))
    if rc != 0:
        _audit(audit, ctx, req, "data.prepare.failed", "allow", f"dj exit={rc}")
        raise RuntimeError(f"data-juicer failed (exit={rc}), log: {work / 'dj.log'}")

    opts = lance_storage_options(req.oss_endpoint, req.bucket, req.access_key,
                                 req.secret_key, req.session_token, req.region)
    n_out = lance_fn(str(cleaned_dir / "cleaned.jsonl"), paths.processed_uri, opts, req.oss_endpoint)
    return {"rows_in": n_in, "rows_written": n_out, "lance_uri": paths.processed_uri}
```

- [x] **步骤 4:跑绿** → 3 passed;**步骤 5:全量** `uv run pytest -q && uv run lint-imports && bash scripts/ci_guards.sh` 全绿
- [x] **步骤 6:提交** `feat(pipelines): run_prepare orchestrator — can() chokepoint + audit + staged seams`

---

### Task 7:一行命令入口 + Makefile + 文档

**Files:**
- 创建:`pipelines/data_prep/__main__.py`
- 修改:`Makefile`(`data-prep` 目标)、`README.md`(§新增"数据准备一行命令")

- [x] **步骤 1:写 `__main__.py`**(argparse → env 取凭据 → x-test-claims 同款 Context 来源:`LITEAI_GROUPS` env 仅 CLI 本地态;真服务化在 Plan 4 经 gateway)

```python
# pipelines/data_prep/__main__.py
"""一行命令:python -m pipelines.data_prep --tar-dir … --dataset cc3m
凭据/endpoint 走 env(OSS_*);调用者身份 v1 CLI 态走 LITEAI_SUB/LITEAI_GROUPS env
(服务化入口在 data-pipeline-service,Plan 4)。"""
import argparse, json, os, sys
import boto3
from libs.identity.context import parse_context
from libs.audit.oss_audit import OssAuditSink, AuditWriter, oss_boto3_config
from pipelines.data_prep.runner import PrepareRequest, run_prepare

def main() -> int:
    ap = argparse.ArgumentParser("data-prep")
    ap.add_argument("--tar-dir", required=True)
    ap.add_argument("--work-dir", default="./.dataprep")
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--enterprise", default="e-0001")
    ap.add_argument("--group", default="g-0001")
    ap.add_argument("--np", type=int, default=int(os.getenv("DJ_NP", os.cpu_count() + 1)))
    a = ap.parse_args()

    ctx = parse_context(sub=os.getenv("LITEAI_SUB", "cli-user"),
                        groups=json.loads(os.getenv("LITEAI_GROUPS",
                            f'["/{a.enterprise}/{a.group}/members"]')))
    endpoint = os.environ["OSS_ENDPOINT"]
    s3 = boto3.client("s3", endpoint_url=endpoint,
                      aws_access_key_id=os.environ["OSS_ACCESS_KEY"],
                      aws_secret_access_key=os.environ["OSS_SECRET_KEY"],
                      aws_session_token=os.getenv("OSS_SESSION_TOKEN"),
                      region_name=os.getenv("OSS_REGION", "cn-hangzhou"),
                      config=oss_boto3_config(endpoint))
    audit = AuditWriter(OssAuditSink(bucket=os.environ["AUDIT_BUCKET"], client=s3))
    req = PrepareRequest(tar_dir=a.tar_dir, work_dir=a.work_dir, bucket=os.environ["DATA_BUCKET"],
                         enterprise_id=a.enterprise, group_id=a.group, dataset=a.dataset,
                         np=a.np, oss_endpoint=endpoint,
                         access_key=os.environ["OSS_ACCESS_KEY"],
                         secret_key=os.environ["OSS_SECRET_KEY"],
                         session_token=os.getenv("OSS_SESSION_TOKEN"),
                         region=os.getenv("OSS_REGION", "cn-hangzhou"))
    out = run_prepare(ctx, req, audit)
    print(json.dumps(out, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

- [x] **步骤 2:Makefile 加** `data-prep: ; uv run python -m pipelines.data_prep $(ARGS)`
- [x] **步骤 3:手动验证(本地 MinIO,fake DJ)** —— `DJ_BIN=true`(系统 /usr/bin/true 模拟 DJ 成功,但 cleaned 为空会报 no rows,故先手放一个 part 文件)或直接以**集成路径**验:`make dev-up` 后用 tests/integration 全绿代替人工;**真 DJ 端到端属云上验收(下一步骤)**。
- [x] **步骤 4:云上端到端(实例已有 dj-venv + 数据)** —— 开机 → 云助手跑:
  `DJ_BIN=/opt/dj-venv/bin/dj-process OSS_ENDPOINT=…-internal… DATA_BUCKET=lite-ai-data-… AUDIT_BUCKET=lite-ai-audit-… python -m pipelines.data_prep --tar-dir /data/raw/cc3m --dataset cc3m`
  期望:打印 `{"rows_in":15138,"rows_written":…,"lance_uri":"s3://…/e-0001/g-0001/processed/cc3m.lance"}`;审计桶出现 `data.prepare` 事件。**这就是 S1 出口① 的正式验收证据。**
- [x] **步骤 5:README 增"§ 数据准备"**(命令 + env 表);**步骤 6:提交** `feat(pipelines): one-command data prep entry`

---

## 验收对照(S1 spec 出口①)

| 出口① 要素 | 任务 |
|---|---|
| 一行命令 | Task 7(`python -m pipelines.data_prep`/`make data-prep`) |
| 清洗(多模态) | Task 3+6(DJ 子进程,spike 算子默认集) |
| → Lance on OSS 隔离路径 | Task 2+5(paths + writer,Spike 1 三约束固化) |
| 经 can() + 审计 | Task 6(唯一出入口;deny 零副作用且留审计) |
| 云上真跑证据 | Task 7 步骤 4 |

Gravitino 注册(出口②)= Plan 3;服务化/SDK(⑤)= Plan 4。

## 自审记录

- 占位符:无 TBD;Task 7 步骤 3 的本地限制(真 DJ 不在主 venv)已如实写明,云上验收是正式证据
- 类型一致:`DatasetPaths`/`PrepareRequest` 字段与 runner/`__main__` 调用一一对齐;`lance_storage_options` 签名在 Task 5/6/7 一致;`EnterpriseId`/`GroupId` 包装与 libs 现状一致
- Spec 覆盖:出口① 全要素见上表;分层契约在 Task 1 先行
