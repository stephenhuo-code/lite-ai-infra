from services.data_pipeline_service.jobs import JobSpec, JobStore

def _spec(jid="job-1", **kw):
    d = dict(job_id=jid, dataset="cc3m", group_id="g-0001", enterprise_id="e-0001",
             role="member", sub="u-alice", tar_dir="/d", np=3, process=None)
    d.update(kw); return JobSpec(**d)

def test_create_then_read_is_queued(tmp_path):
    s = JobStore(str(tmp_path)); s.create(_spec())
    r = s.read("job-1")
    assert r["status"] == "queued" and r["dataset"] == "cc3m" and r["enterprise_id"] == "e-0001"
    assert r["created_at"] and r["rows_written"] is None and r["terminal"] is False

def test_update_terminal_fields(tmp_path):
    s = JobStore(str(tmp_path)); s.create(_spec())
    s.update("job-1", "succeeded", rows_in=15138, rows_written=15000, lance_uri="s3://b/x.lance")
    r = s.read("job-1")
    assert r["status"] == "succeeded" and r["rows_written"] == 15000 and r["lance_uri"].endswith(".lance")
    assert r["terminal"] is True

def test_running_jobs_lists_pid(tmp_path):
    s = JobStore(str(tmp_path)); s.create(_spec())
    s.update("job-1", "running", pid=4242)
    assert s.running_jobs() == [("job-1", 4242)]

def test_oldest_queued_and_running_count(tmp_path):
    s = JobStore(str(tmp_path))
    s.create(_spec("job-1")); s.create(_spec("job-2"))
    assert s.running_count() == 0
    assert s.oldest_queued() == "job-1"          # FIFO(按 created_at)
    s.update("job-1", "running")
    assert s.running_count() == 1 and s.oldest_queued() == "job-2"

def test_read_unknown_is_none(tmp_path):
    assert JobStore(str(tmp_path)).read("nope") is None

def test_load_spec_roundtrip(tmp_path):
    s = JobStore(str(tmp_path)); s.create(_spec(process=[{"a": 1}]))
    sp = s.load_spec("job-1")
    assert sp.tar_dir == "/d" and sp.role == "member" and sp.process == [{"a": 1}]
