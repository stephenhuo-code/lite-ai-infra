# tests/services/data_pipeline/test_list_jobs.py —— Task 7:GET /v1/data/jobs(can() 过滤 + 分页 + fail-closed)
import json

import pytest
from fastapi.testclient import TestClient

from services.data_pipeline_service.app import build_app
from services.data_pipeline_service.jobs import JobStore


class MemSink:
    def __init__(self):
        self.items = []

    def put(self, key, body):
        self.items.append((key, body))


@pytest.fixture(autouse=True)
def _seam(monkeypatch):
    monkeypatch.setenv("LITEAI_ALLOW_TEST_CLAIMS", "1")


class _FakeMeta:
    def get_dataset(self, catalog, schema, name, *, bearer):
        return {"name": name, "kind": "raw", "location": f"s3://b/e-0001/g-0001/raw/{name}/"}


def _client(tmp_path):
    from libs.audit.oss_audit import AuditWriter
    from services.data_pipeline_service.scheduler import SubprocessJobRunner
    store = JobStore(str(tmp_path))
    runner = SubprocessJobRunner(store, spawn=lambda argv, **kw: None)
    return TestClient(build_app(runner=runner, audit=AuditWriter(MemSink()), metadata=_FakeMeta())), store


def _hdr(sub, gid):
    return {"x-test-claims": json.dumps({"sub": sub, "groups": [f"/e-0001/{gid}/members"]})}


def _submit(c, sub, gid):
    return c.post("/v1/data/prepare", headers=_hdr(sub, gid),
                  json={"dataset": "cc3m", "source_dataset": "cc3m-raw"}).json()["id"]


def test_lists_only_callers_own_jobs(tmp_path):
    # owner 模型(ADR-024):列表只见自己 owner 的作业;同企业他人的(不同 owner)经 can() 过滤掉。
    c, store = _client(tmp_path)
    j1 = _submit(c, "u-alice", "g-0001")
    j2 = _submit(c, "u-alice", "g-0001")
    j3 = _submit(c, "u-bob", "g-0002")        # 他人(同企业)— alice 非 owner,不可见
    r = c.get("/v1/data/jobs", headers=_hdr("u-alice", "g-0001"))
    assert r.status_code == 200
    body = r.json()
    ids = {j["id"] for j in body["jobs"]}
    assert ids == {j1, j2} and body["total"] == 2          # can() 按 owner 过滤掉 u-bob 的
    assert all(j["owner_user"] == "u-alice" for j in body["jobs"])
    assert j3 not in ids


def test_status_filter(tmp_path):
    c, store = _client(tmp_path)
    j1 = _submit(c, "u-alice", "g-0001")
    j2 = _submit(c, "u-alice", "g-0001")
    store.update(j1, "succeeded", rows_written=10)
    store.update(j2, "failed", error="boom")
    r = c.get("/v1/data/jobs?status=succeeded", headers=_hdr("u-alice", "g-0001"))
    body = r.json()
    assert body["total"] == 1 and [j["id"] for j in body["jobs"]] == [j1]


def test_pagination_total_is_filtered_count(tmp_path):
    c, store = _client(tmp_path)
    _submit(c, "u-alice", "g-0001")
    _submit(c, "u-alice", "g-0001")
    r = c.get("/v1/data/jobs?limit=1&offset=1", headers=_hdr("u-alice", "g-0001"))
    body = r.json()
    assert len(body["jobs"]) == 1 and body["total"] == 2   # total 为过滤后总数(非页大小)


def test_corrupt_job_missing_spec_is_failclosed(tmp_path):
    # I-2 fail-closed:spec.json 缺失(read 返回 enterprise_id=None)→ 必被排除,不漏给任何企业
    c, store = _client(tmp_path)
    j1 = _submit(c, "u-alice", "g-0001")
    # 构造损坏 job:只写 status.json,无 spec.json
    bad = store.job_dir("job-broken")
    bad.mkdir(parents=True, exist_ok=True)
    (bad / "status.json").write_text(json.dumps(
        {"status": "running", "created_at": "2026-06-19T00:00:00+00:00", "updated_at": "2026-06-19T00:00:00+00:00"}))
    assert store.read("job-broken")["enterprise_id"] is None   # 投影确为 None
    r = c.get("/v1/data/jobs", headers=_hdr("u-alice", "g-0001"))
    body = r.json()
    ids = {j["id"] for j in body["jobs"]}
    assert ids == {j1} and body["total"] == 1                  # 损坏 job 被排除

def test_unauthenticated_401(tmp_path):
    c, _ = _client(tmp_path)
    assert c.get("/v1/data/jobs").status_code == 401


def test_pagination_bounds_enforced(tmp_path):
    # 契约边界强制(FastAPI 默认不验 schema 边界,须 Query(ge/le)):越界 → 422
    c, _ = _client(tmp_path)
    h = _hdr("u-alice", "g-0001")
    assert c.get("/v1/data/jobs?limit=999999", headers=h).status_code == 422   # > maximum 200
    assert c.get("/v1/data/jobs?limit=0", headers=h).status_code == 422        # < 1
    assert c.get("/v1/data/jobs?offset=-5", headers=h).status_code == 422      # 负 offset
    assert c.get("/v1/data/jobs?limit=200&offset=0", headers=h).status_code == 200
