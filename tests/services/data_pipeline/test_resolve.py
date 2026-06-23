import json, pytest
import httpx
from fastapi.testclient import TestClient
from services.data_pipeline_service.app import build_app


class MemSink:
    def __init__(self): self.items = []
    def put(self, key, body): self.items.append((key, body))


class _FakeMeta:
    """fake metadata client:None → get_dataset 抛 404;否则返回给定 _dataset。"""
    def __init__(self, ds): self._ds = ds; self.calls = []

    def get_dataset(self, catalog, schema, name, *, bearer):
        self.calls.append((catalog, schema, name, bearer))
        if self._ds is None:
            raise httpx.HTTPStatusError(
                "404", request=httpx.Request("GET", "http://x"),
                response=httpx.Response(404))
        return self._ds


class _FakeRunner:
    def __init__(self): self.spec = None
    def submit(self, spec): self.spec = spec
    def get(self, jid): return {"id": jid, "enterprise_id": "e-0001",
                                "status": "queued", "terminal": False}


@pytest.fixture(autouse=True)
def _seam(monkeypatch): monkeypatch.setenv("LITEAI_ALLOW_TEST_CLAIMS", "1")


def _client(meta):
    from libs.audit.oss_audit import AuditWriter
    runner = _FakeRunner()
    app = build_app(runner=runner, audit=AuditWriter(MemSink()), metadata=meta)
    return TestClient(app), runner


def _hdr(sub, groups): return {"x-test-claims": json.dumps({"sub": sub, "groups": groups})}


def test_raw_source_resolves_location_into_spec(tmp_path):
    meta = _FakeMeta({"name": "cc3m-raw", "kind": "raw",
                      "location": "s3://b/e-0001/g-0001/raw/cc3m-raw/"})
    c, runner = _client(meta)
    r = c.post("/v1/data/prepare", headers=_hdr("u-a", ["/e-0001/g-0001/members"]),
               json={"dataset": "cc3m", "group_id": "g-0001", "source_dataset": "cc3m-raw"})
    assert r.status_code == 202
    assert runner.spec.source_location == "s3://b/e-0001/g-0001/raw/cc3m-raw/"
    assert runner.spec.dataset == "cc3m"               # 产出名保留
    assert meta.calls[0][2] == "cc3m-raw"              # 按 source_dataset 名解析


def test_processed_source_rejected_400(tmp_path):
    meta = _FakeMeta({"name": "cc3m", "kind": "processed",
                      "location": "s3://b/e-0001/g-0001/processed/cc3m/"})
    c, runner = _client(meta)
    r = c.post("/v1/data/prepare", headers=_hdr("u-a", ["/e-0001/g-0001/members"]),
               json={"dataset": "out", "group_id": "g-0001", "source_dataset": "cc3m"})
    assert r.status_code == 400
    assert runner.spec is None                          # 零副作用:未提交


def test_missing_source_400(tmp_path):
    meta = _FakeMeta(None)                               # get_dataset 抛 404
    c, runner = _client(meta)
    r = c.post("/v1/data/prepare", headers=_hdr("u-a", ["/e-0001/g-0001/members"]),
               json={"dataset": "out", "group_id": "g-0001", "source_dataset": "nope"})
    assert r.status_code == 400
    assert runner.spec is None
