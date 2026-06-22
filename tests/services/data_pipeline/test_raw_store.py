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
