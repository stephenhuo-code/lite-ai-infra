from pathlib import Path
from pipelines.data_prep.oss_fetch import fetch_oss_tars

class _FakeS3:
    def __init__(self, keys): self._keys = keys
    def get_paginator(self, op):
        keys = self._keys
        class _P:
            def paginate(self, Bucket, Prefix):
                yield {"Contents": [{"Key": k} for k in keys if k.startswith(Prefix)]}
        return _P()
    def download_file(self, Bucket, Key, Filename):
        Path(Filename).write_bytes(b"fake-tar")

def test_fetch_only_tars_under_prefix(tmp_path):
    s3 = _FakeS3(["e-0001/g-0001/raw/coco/a.tar", "e-0001/g-0001/raw/coco/b.tar",
                  "e-0001/g-0001/raw/coco/notes.txt", "e-0001/g-0002/raw/x/c.tar"])
    n = fetch_oss_tars(s3, bucket="lite-ai", prefix="e-0001/g-0001/raw/coco/", dest_dir=str(tmp_path))
    assert sorted(p.name for p in tmp_path.glob("*.tar")) == ["a.tar", "b.tar"]
    assert n == 2

def test_fetch_zero_tars_returns_zero(tmp_path):
    s3 = _FakeS3(["e-0001/g-0001/raw/coco/readme.md"])
    assert fetch_oss_tars(s3, bucket="lite-ai", prefix="e-0001/g-0001/raw/coco/", dest_dir=str(tmp_path)) == 0
