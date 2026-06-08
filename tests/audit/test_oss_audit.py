# tests/audit/test_oss_audit.py
import json
from libs.audit.oss_audit import AuditWriter, AuditEvent, _audit_key

EV = AuditEvent(ts="2026-06-08T00:00:00Z", enterprise_id="e-0001", group_id="g-0001",
                actor_user="u-alice", actor_role="member", action="job.cancel",
                resource_uri="job/abc", decision="allow", override=False, reason="", metadata={})

class MemoryAuditSink:
    def __init__(self): self.items = []
    def put(self, key, body): self.items.append((key, body))

class RaisingSink:
    def put(self, key, body): raise RuntimeError("oss down")

def test_audit_key_partitioned_by_date():
    k = _audit_key(EV)
    assert k.startswith("audit/2026/06/08/") and k.endswith(".jsonl")

def test_write_returns_key_and_records():
    sink = MemoryAuditSink()
    key = AuditWriter(sink).write(EV)
    assert key and len(sink.items) == 1
    assert json.loads(sink.items[0][1])["action"] == "job.cancel"

def test_write_never_raises_into_caller():
    # 尽力写：sink 抛错也不得抛给调用方（ADR-010 v1 非原子）
    assert AuditWriter(RaisingSink()).write(EV) is None
