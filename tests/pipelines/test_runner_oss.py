import json
from libs.identity.context import parse_context
from libs.audit.oss_audit import AuditWriter
from pipelines.data_prep.runner import PrepareRequest, run_prepare

class MemoryAuditSink:
    def __init__(self): self.items = []
    def put(self, key, body): self.items.append((key, body))

def _req(tmp_path, **kw):
    return PrepareRequest(tar_dir=str(tmp_path / "tars"), work_dir=str(tmp_path / "work"),
                          bucket="bkt", enterprise_id="e-0001", group_id="g-0001",
                          dataset="coco", np=3, oss_endpoint="http://localhost:9000",
                          access_key="ak", secret_key="sk", **kw)

def test_source_location_fetches_from_oss_then_converts_local(tmp_path):
    sink = MemoryAuditSink(); calls = []
    fetch_seen = {}
    def fake_fetch(s3, *, bucket, prefix, dest_dir):
        fetch_seen.update(bucket=bucket, prefix=prefix, dest_dir=dest_dir)
        return 2
    ctx = parse_context("u-alice", ["/e-0001/g-0001/members"])
    req = _req(tmp_path, source_location="s3://lite-ai/e-0001/g-0001/raw/coco/")
    out = run_prepare(
        ctx, req, AuditWriter(sink),
        convert_fn=lambda tar, o: calls.append(("convert", tar)) or 5,
        dj_fn=lambda r, l: calls.append(("dj", r)) or 0,
        lance_fn=lambda c, uri, opts, ep: calls.append(("lance", uri)) or 5,
        fetch_fn=fake_fetch,
        build_s3_fn=lambda *a, **k: object())
    # fetch 收到从 source_location 拆出的 bucket + key 前缀
    assert fetch_seen["bucket"] == "lite-ai"
    assert fetch_seen["prefix"] == "e-0001/g-0001/raw/coco/"
    # convert 收到本地 work_dir/tars(非 OSS uri,非原 tar_dir)
    convert_arg = [c[1] for c in calls if c[0] == "convert"][0]
    assert convert_arg == str(tmp_path / "work" / "tars")
    assert fetch_seen["dest_dir"] == str(tmp_path / "work" / "tars")
    assert out["lance_uri"].endswith("processed/coco.lance")
    assert json.loads(sink.items[0][1])["decision"] == "allow"

def test_tar_dir_path_unchanged_when_no_source_location(tmp_path):
    sink = MemoryAuditSink(); calls = []
    fetched = {"called": False}
    def fake_fetch(s3, *, bucket, prefix, dest_dir):
        fetched["called"] = True
        return 0
    ctx = parse_context("u-alice", ["/e-0001/g-0001/members"])
    req = _req(tmp_path)  # no source_location → 旧行为
    out = run_prepare(
        ctx, req, AuditWriter(sink),
        convert_fn=lambda tar, o: calls.append(("convert", tar)) or 5,
        dj_fn=lambda r, l: 0,
        lance_fn=lambda c, uri, opts, ep: 5,
        fetch_fn=fake_fetch)
    assert fetched["called"] is False
    assert [c[1] for c in calls if c[0] == "convert"][0] == str(tmp_path / "tars")
    assert out["lance_uri"].endswith("processed/coco.lance")

def test_source_location_zero_tars_raises(tmp_path):
    import pytest
    sink = MemoryAuditSink()
    ctx = parse_context("u-alice", ["/e-0001/g-0001/members"])
    req = _req(tmp_path, source_location="s3://lite-ai/e-0001/g-0001/raw/coco/")
    with pytest.raises(RuntimeError, match="no .tar"):
        run_prepare(
            ctx, req, AuditWriter(sink),
            convert_fn=lambda tar, o: 5, dj_fn=lambda r, l: 0,
            lance_fn=lambda c, uri, opts, ep: 5,
            fetch_fn=lambda s3, *, bucket, prefix, dest_dir: 0,
            build_s3_fn=lambda *a, **k: object())
