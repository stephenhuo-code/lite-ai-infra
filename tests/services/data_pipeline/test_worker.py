import pytest
from libs.identity.ids import EnterpriseId, GroupId
from services.data_pipeline_service.jobs import JobSpec, JobStore
from services.data_pipeline_service import worker as W

@pytest.fixture(autouse=True)
def _oss_env(monkeypatch):
    # worker 构造 PrepareRequest 时从 env 读凭据/桶(同 pipelines/data_prep/__main__.py)
    for k, v in {"DATA_BUCKET": "b", "AUDIT_BUCKET": "b", "OSS_ENDPOINT": "http://localhost:9000",
                 "OSS_ACCESS_KEY": "ak", "OSS_SECRET_KEY": "sk"}.items():
        monkeypatch.setenv(k, v)

def _seed(tmp_path, **kw):
    store = JobStore(str(tmp_path))
    sp = JobSpec("job-1", "cc3m", "g-0001", "e-0001", "member", "u-a", "/d", 3, kw.get("process"))
    store.create(sp); store.update("job-1", "running")
    return store

def test_success_writes_terminal(tmp_path, monkeypatch):
    store = _seed(tmp_path, process=[{"a": 1}])
    seen = {}
    def fake_run_prepare(ctx, req, audit):
        seen["ctx_role"] = ctx.role_in(EnterpriseId("e-0001"), GroupId("g-0001"))
        seen["process"] = req.process
        return {"rows_in": 15138, "rows_written": 15000, "lance_uri": "s3://b/cc3m.lance"}
    monkeypatch.setattr(W, "run_prepare", fake_run_prepare)
    monkeypatch.setattr(W, "_audit_writer", lambda: None)
    W.run_job(str(store.job_dir("job-1")))
    r = store.read("job-1")
    assert r["status"] == "succeeded" and r["rows_written"] == 15000 and r["lance_uri"].endswith(".lance")
    assert seen["ctx_role"] == "member"          # 快照角色重建正确
    assert seen["process"] == [{"a": 1}]         # spec.process 透传给 run_prepare

def test_permission_error_marks_failed(tmp_path, monkeypatch):
    store = _seed(tmp_path)
    def boom(ctx, req, audit): raise PermissionError("cross-group")
    monkeypatch.setattr(W, "run_prepare", boom); monkeypatch.setattr(W, "_audit_writer", lambda: None)
    W.run_job(str(store.job_dir("job-1")))
    r = store.read("job-1")
    assert r["status"] == "failed" and "cross-group" in r["error"]

def test_generic_error_marks_failed(tmp_path, monkeypatch):
    store = _seed(tmp_path)
    monkeypatch.setattr(W, "run_prepare", lambda *a: (_ for _ in ()).throw(RuntimeError("dj exit=1")))
    monkeypatch.setattr(W, "_audit_writer", lambda: None)
    W.run_job(str(store.job_dir("job-1")))
    assert store.read("job-1")["status"] == "failed"

def test_missing_spec_marks_failed_not_crash(tmp_path):
    # 损坏 job dir(spec.json 缺失):worker 写 failed 终态而非崩成无终态孤儿 running
    store = JobStore(str(tmp_path)); (tmp_path / "job-1").mkdir()
    W.run_job(str(store.job_dir("job-1")))
    r = store.read("job-1")
    assert r["status"] == "failed" and "spec.json" in r["error"]
