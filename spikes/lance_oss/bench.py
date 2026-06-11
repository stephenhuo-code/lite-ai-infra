# /// script
# requires-python = ">=3.12"
# dependencies = ["pylance>=0.18", "pyarrow>=17", "numpy>=2", "boto3>=1.35"]
# ///
"""
Spike 1 —— Lance on 对象存储 读写延迟 harness（本地 MinIO 基线 / 上云零改）。

本地证什么:Lance API（写 / 全扫 / 列裁剪 / 随机访问）打 S3 兼容对象存储跑通,
            并给出**本地基线延迟**(局域网下限)。
本地证不了:真阿里云 OSS 的跨网延迟、100GB 规模吞吐、JindoFS/缓存降级结论
            —— 那是出口① 的判据,必须上云(改下面的 env 即可,脚本零改)。

跑(本地 MinIO,需 `make dev-up`):
    uv run spikes/lance_oss/bench.py
上云(同一脚本,改 env):
    OSS_ENDPOINT=https://oss-cn-hangzhou.aliyuncs.com OSS_ACCESS_KEY=... \
    OSS_SECRET_KEY=... OSS_REGION=cn-hangzhou AUDIT_BUCKET=<bucket> \
    SPIKE_ROWS=2000000 SPIKE_DIM=768 uv run spikes/lance_oss/bench.py

调规模:SPIKE_ROWS（默认 20000）、SPIKE_DIM（默认 256）。
"""
from __future__ import annotations
import os, time, uuid
import numpy as np
import pyarrow as pa
import boto3
from botocore.config import Config
import lance

ENDPOINT = os.getenv("OSS_ENDPOINT", "http://localhost:9000")
ACCESS = os.getenv("OSS_ACCESS_KEY", "minio")
SECRET = os.getenv("OSS_SECRET_KEY", "minio123")
REGION = os.getenv("OSS_REGION", "us-east-1")
BUCKET = os.getenv("SPIKE_BUCKET", os.getenv("AUDIT_BUCKET", "lance-spike"))
ROWS = int(os.getenv("SPIKE_ROWS", "20000"))
DIM = int(os.getenv("SPIKE_DIM", "256"))
TAKE_N = int(os.getenv("SPIKE_TAKE_N", "1000"))

_HTTP = ENDPOINT.startswith("http://")
# Spike C 实测:真 OSS 拒 path-style → aliyuncs.com 用 virtual-hosted;MinIO 用 path
_VIRTUAL = "aliyuncs.com" in ENDPOINT
# rust object_store 怪癖:virtual-hosted 模式下 endpoint 必须自带 bucket 域名,
# 否则 list 等请求打到根域被 OSS 当成 ListBuckets → 403(2026-06-12 实测)
_scheme, _host = ENDPOINT.split("://", 1)
_LANCE_ENDPOINT = f"{_scheme}://{BUCKET}.{_host}" if _VIRTUAL else ENDPOINT
STORAGE_OPTIONS = {
    "access_key_id": ACCESS,
    "secret_access_key": SECRET,
    "endpoint": _LANCE_ENDPOINT,
    "region": REGION,
    "allow_http": "true" if _HTTP else "false",
    "virtual_hosted_style_request": "true" if _VIRTUAL else "false",
}
if os.getenv("OSS_SESSION_TOKEN"):   # 实例 RAM 角色的 STS 临时凭据
    STORAGE_OPTIONS["session_token"] = os.environ["OSS_SESSION_TOKEN"]


def _ensure_bucket():
    s3 = boto3.client("s3", endpoint_url=ENDPOINT, aws_access_key_id=ACCESS,
                      aws_secret_access_key=SECRET, region_name=REGION,
                      aws_session_token=os.getenv("OSS_SESSION_TOKEN"),
                      config=Config(s3={"addressing_style": "virtual" if _VIRTUAL else "path"},
                                    request_checksum_calculation="when_required",
                                    response_checksum_validation="when_required"))
    try:
        s3.create_bucket(Bucket=BUCKET)
    except Exception:
        pass  # 已存在即可


def _make_table(rows: int, dim: int) -> pa.Table:
    rng = np.random.default_rng(42)
    vecs = rng.standard_normal((rows, dim), dtype=np.float32)
    vec_col = pa.FixedSizeListArray.from_arrays(pa.array(vecs.reshape(-1)), dim)
    return pa.table({
        "id": pa.array(np.arange(rows, dtype=np.int64)),
        "vec": vec_col,
        "text": pa.array([f"sample-{i}" for i in range(rows)]),
    })


def _timed(label: str, fn):
    t0 = time.perf_counter()
    out = fn()
    dt = time.perf_counter() - t0
    return label, dt, out


def main():
    bytes_total = ROWS * DIM * 4
    mb = bytes_total / 1e6
    uri = f"s3://{BUCKET}/lance_oss_bench/{uuid.uuid4().hex[:8]}.lance"
    print(f"== Lance on object store ==  endpoint={ENDPOINT}  bucket={BUCKET}")
    print(f"   rows={ROWS:,}  dim={DIM}  vec≈{mb:.1f} MB  uri={uri}\n")

    _ensure_bucket()
    tbl = _make_table(ROWS, DIM)

    results = []
    # 1) 写
    results.append(_timed("write", lambda: lance.write_dataset(
        tbl, uri, storage_options=STORAGE_OPTIONS, mode="overwrite"))[:2])
    ds = lance.dataset(uri, storage_options=STORAGE_OPTIONS)

    # 2) 全列顺序扫描
    results.append(_timed("scan(full)", lambda: ds.to_table().num_rows)[:2])
    # 3) 列裁剪(只读 id)
    results.append(_timed("scan(proj=id)", lambda: ds.to_table(columns=["id"]).num_rows)[:2])
    # 4) 随机访问 TAKE_N 行
    rng = np.random.default_rng(7)
    idx = rng.integers(0, ROWS, size=min(TAKE_N, ROWS)).tolist()
    results.append(_timed("random_take", lambda: ds.take(idx, columns=["id", "vec"]).num_rows)[:2])

    print(f"{'op':<16}{'seconds':>10}{'MB/s':>12}{'note':>22}")
    print("-" * 60)
    for label, dt in results:
        if label == "write":
            print(f"{label:<16}{dt:>10.3f}{mb/dt:>12.1f}{'full vec payload':>22}")
        elif label == "scan(full)":
            print(f"{label:<16}{dt:>10.3f}{mb/dt:>12.1f}{'all columns':>22}")
        elif label == "scan(proj=id)":
            print(f"{label:<16}{dt:>10.3f}{'-':>12}{'column pruning':>22}")
        else:
            per = dt / max(1, len(idx)) * 1e3
            print(f"{label:<16}{dt:>10.3f}{'-':>12}{f'{per:.3f} ms/row x{len(idx)}':>22}")

    print("\n注:以上为**本地 MinIO 基线**(下限)。出口① 判据=真 OSS 跨网延迟 + 100GB 吞吐 + 降级结论,需上云复跑。")


if __name__ == "__main__":
    main()
