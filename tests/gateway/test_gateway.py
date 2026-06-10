# tests/gateway/test_gateway.py
import json
import pytest
from fastapi.testclient import TestClient
from libs.audit.oss_audit import AuditWriter

class MemoryAuditSink:                       # 测试 double（零依赖，不用 moto/MinIO）
    def __init__(self): self.items = []
    def put(self, key, body): self.items.append((key, body))

@pytest.fixture(autouse=True)
def _enable_test_claims(monkeypatch):
    # 测试 seam 默认关闭(default-deny);单测显式开启
    monkeypatch.setenv("LITEAI_ALLOW_TEST_CLAIMS", "1")

def _client(sink):
    from services.gateway.app import build_app
    return TestClient(build_app(audit=AuditWriter(sink)))

def _hdr(sub, groups):
    return {"x-test-claims": json.dumps({"sub": sub, "groups": groups})}

def test_unauthenticated_returns_401():
    client = _client(MemoryAuditSink())
    assert client.request("DELETE", "/v1/jobs/abc").status_code == 401     # AC-18

def test_seam_disabled_by_default_rejects_test_claims(monkeypatch):
    # 回归锁:不显式开 seam 时,x-test-claims 必须被无视 → 401(生产 default-deny)
    monkeypatch.delenv("LITEAI_ALLOW_TEST_CLAIMS", raising=False)
    client = _client(MemoryAuditSink())
    r = client.request("DELETE", "/v1/jobs/job-1", headers=_hdr("u-mallory", ["/e-0001/admins"]))
    assert r.status_code == 401

def test_seam_malformed_claims_return_401_not_500():
    client = _client(MemoryAuditSink())
    r = client.request("DELETE", "/v1/jobs/job-1", headers={"x-test-claims": "{not json"})
    assert r.status_code == 401

def test_allowed_request_passes_and_audits():
    sink = MemoryAuditSink(); client = _client(sink)
    r = client.request("DELETE", "/v1/jobs/job-1", headers=_hdr("u-alice", ["/e-0001/g-0001/members"]))
    assert r.status_code == 200                              # AC-1
    assert len(sink.items) == 1 and sink.items[0][0].startswith("audit/")

def test_cross_enterprise_denied_403_and_audited():
    sink = MemoryAuditSink(); client = _client(sink)
    r = client.request("DELETE", "/v1/jobs/e-0099:job-9", headers=_hdr("u-alice", ["/e-0001/g-0001/members"]))
    assert r.status_code == 403                              # AC-6/15
    assert "cross-enterprise" in r.json()["reason"]
    assert len(sink.items) == 1                              # deny 也审计
    assert json.loads(sink.items[0][1])["decision"] == "deny"

def test_me_orgs_matches_contract():
    client = _client(MemoryAuditSink())
    r = client.get("/v1/me/orgs", headers=_hdr("u-alice", ["/e-0001/g-0001/members"]))
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"user", "is_platform_admin", "memberships"}
    assert body["memberships"][0] == {"enterprise_id": "e-0001", "group_id": "g-0001", "role": "member"}
