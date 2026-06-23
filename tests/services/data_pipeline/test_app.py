import json, pytest
from fastapi.testclient import TestClient
from services.data_pipeline_service.app import build_app
from services.data_pipeline_service.jobs import JobStore

class MemSink:
    def __init__(self): self.items = []
    def put(self, key, body): self.items.append((key, body))

@pytest.fixture(autouse=True)
def _seam(monkeypatch): monkeypatch.setenv("LITEAI_ALLOW_TEST_CLAIMS", "1")

class _FakeMeta:
    """fake metadata client:prepare 按名解析源 raw 数据集 location(catalog-driven)。"""
    def get_dataset(self, catalog, schema, name, *, bearer):
        return {"name": name, "kind": "raw", "location": f"s3://b/e-0001/g-0001/raw/{name}/"}

def _client(tmp_path):
    from libs.audit.oss_audit import AuditWriter
    from services.data_pipeline_service.scheduler import SubprocessJobRunner
    store = JobStore(str(tmp_path)); sink = MemSink()
    runner = SubprocessJobRunner(store, spawn=lambda argv, **kw: None)   # 不真 spawn
    return TestClient(build_app(runner=runner, audit=AuditWriter(sink), metadata=_FakeMeta())), store, sink

def _hdr(sub, groups): return {"x-test-claims": json.dumps({"sub": sub, "groups": groups})}

def test_submit_returns_202_job(tmp_path):
    c, store, _ = _client(tmp_path)
    r = c.post("/v1/data/prepare", headers=_hdr("u-a", ["/e-0001/g-0001/members"]),
               json={"dataset": "cc3m", "group_id": "g-0001", "source_dataset": "cc3m-raw"})
    assert r.status_code == 202
    body = r.json()
    assert body["id"] and body["enterprise_id"] == "e-0001" and body["status"] in ("queued", "running")
    assert store.read(body["id"]) is not None        # 已入库

def test_unauthorized_submit_denied_no_side_effect(tmp_path):
    # 企业从 caller token 推导(enterprise_of),跨企业 POST 结构上不可能;
    # 本端点 can() deny 边界 = 跨组(caller 在 e-0001/g-0002,提交 g-0001)。
    # deny → 403 + 零副作用 + deny 审计(plan 原用 e-0099/g-0001 实为同组放行,已修正)。
    c, store, sink = _client(tmp_path)
    r = c.post("/v1/data/prepare", headers=_hdr("u-x", ["/e-0001/g-0002/members"]),
               json={"dataset": "cc3m", "group_id": "g-0001", "source_dataset": "cc3m-raw"})
    assert r.status_code == 403
    assert list(store.root.iterdir()) == []          # 零副作用:无作业落库
    assert json.loads(sink.items[0][1])["decision"] == "deny"   # deny 仍审计

def test_get_same_group_ok_cross_group_403_unknown_404(tmp_path):
    c, store, _ = _client(tmp_path)
    jid = c.post("/v1/data/prepare", headers=_hdr("u-a", ["/e-0001/g-0001/members"]),
                 json={"dataset": "cc3m", "group_id": "g-0001", "source_dataset": "cc3m-raw"}).json()["id"]
    assert c.get(f"/v1/data/jobs/{jid}", headers=_hdr("u-a", ["/e-0001/g-0001/members"])).status_code == 200
    assert c.get(f"/v1/data/jobs/{jid}", headers=_hdr("u-b", ["/e-0001/g-0002/members"])).status_code == 403
    assert c.get("/v1/data/jobs/nope", headers=_hdr("u-a", ["/e-0001/g-0001/members"])).status_code == 404

def test_prepare_stores_source_dataset_and_job_projects_it(tmp_path):
    # 血缘(US3-AC1/SC-003):prepare 把用户选的源 source_dataset 存进 spec,
    # Job 读模型暴露它 → 前端注册产物 derived_from 取真实来源(非产出名)。
    c, store, _ = _client(tmp_path)
    body = c.post("/v1/data/prepare", headers=_hdr("u-a", ["/e-0001/g-0001/members"]),
                  json={"dataset": "coco-clean", "group_id": "g-0001", "source_dataset": "coco"}).json()
    assert store.load_spec(body["id"]).source_dataset == "coco"   # spec 存源名
    assert body["source_dataset"] == "coco"                       # Job 投影暴露源名(≠产出名 coco-clean)

def test_process_override_persisted(tmp_path):
    c, store, _ = _client(tmp_path)
    jid = c.post("/v1/data/prepare", headers=_hdr("u-a", ["/e-0001/g-0001/members"]),
                 json={"dataset": "cc3m", "group_id": "g-0001", "source_dataset": "cc3m-raw",
                       "process": [{"text_length_filter": {"min_len": 9}}]}).json()["id"]
    assert store.load_spec(jid).process == [{"text_length_filter": {"min_len": 9}}]
