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
                          bucket="bkt", enterprise_id="e-0001",
                          dataset="cc3m", np=3, oss_endpoint="http://localhost:9000",
                          access_key="ak", secret_key="sk", **kw)

def _ok_fakes(calls):
    return dict(
        convert_fn=lambda tar, out: calls.append(("convert", tar)) or 5,
        dj_fn=lambda recipe_path, log_path: calls.append(("dj", recipe_path)) or 0,
        lance_fn=lambda cleaned, uri, opts, ep: calls.append(("lance", uri)) or 5)

def test_denied_caller_gets_no_side_effects(tmp_path):
    sink = MemoryAuditSink(); calls = []
    ctx = parse_context("u-x", ["e-0099"], [])       # 跨企业
    with pytest.raises(PermissionError):
        run_prepare(ctx, _req(tmp_path), AuditWriter(sink), **_ok_fakes(calls))
    assert calls == []                                            # 无任何副作用
    assert len(sink.items) == 1                                   # deny 也审计
    assert json.loads(sink.items[0][1])["decision"] == "deny"

def test_happy_path_runs_stages_and_audits(tmp_path):
    sink = MemoryAuditSink(); calls = []
    ctx = parse_context("u-alice", ["e-0001"], [])
    out = run_prepare(ctx, _req(tmp_path), AuditWriter(sink), **_ok_fakes(calls))
    assert [c[0] for c in calls] == ["convert", "dj", "lance"]
    assert out["rows_written"] == 5
    assert out["lance_uri"] == "s3://bkt/e-0001/u-alice/processed/cc3m.lance"   # owner 路径(ADR-024)
    assert json.loads(sink.items[0][1])["decision"] == "allow"

def test_dj_failure_audited_and_raises(tmp_path):
    sink = MemoryAuditSink(); calls = []
    ctx = parse_context("u-alice", ["e-0001"], [])
    fakes = _ok_fakes(calls); fakes["dj_fn"] = lambda r, l: 1     # 非零退出
    with pytest.raises(RuntimeError):
        run_prepare(ctx, _req(tmp_path), AuditWriter(sink), **fakes)
    assert any(json.loads(b)["action"] == "data.prepare.failed" for _, b in sink.items)

def test_process_override_passed_to_recipe(tmp_path, monkeypatch):
    seen = {}
    import pipelines.data_prep.runner as R
    monkeypatch.setattr(R, "build_recipe",
                        lambda inp, out, np, process=None: seen.update(process=process) or "x: 1")
    sink = MemoryAuditSink(); calls = []
    ctx = parse_context("u-alice", ["e-0001"], [])
    req = _req(tmp_path, process=[{"text_length_filter": {"min_len": 9}}])
    run_prepare(ctx, req, AuditWriter(sink), **_ok_fakes(calls))
    assert seen["process"] == [{"text_length_filter": {"min_len": 9}}]
