# pipelines/data_prep/lance_writer.py
"""清洗产物(目录式 jsonl)→ Lance dataset on 对象存储。

Spike 1(spikes/lance_oss/RESULTS-aliyun.md)三条实测约束在此固化:
1. OSS 拒 path-style → virtual-hosted;MinIO 反之;
2. virtual-hosted 模式下 lance/object_store 要求 endpoint 自带 bucket 域名;
3. OSS 无 If-None-Match 条件写 → manifest 提交走 commit_lock
   (单写者 no-op 锁安全;多写者真锁属 S2a 课题)。
"""
from __future__ import annotations

import contextlib
import glob
import json

import lance
import pyarrow as pa


def _is_oss(endpoint: str) -> bool:
    return "aliyuncs.com" in endpoint


def needs_commit_lock(endpoint: str) -> bool:
    return _is_oss(endpoint)


def lance_storage_options(endpoint: str, bucket: str, access_key: str, secret_key: str,
                          session_token: str | None = None, region: str = "cn-hangzhou") -> dict:
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
    """DJ 输出(目录内 *.json* part 文件)→ Lance dataset。返回写入行数。"""
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
