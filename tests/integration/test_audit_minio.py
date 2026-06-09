# tests/integration/test_audit_minio.py
import json, pytest
from libs.audit.oss_audit import OssAuditSink, AuditWriter, AuditEvent
pytestmark = pytest.mark.integration


def test_audit_real_minio_write_read(minio_s3, minio_bucket):
    w = AuditWriter(OssAuditSink(bucket=minio_bucket, client=minio_s3))
    ev = AuditEvent(ts="2026-06-08T00:00:00Z", enterprise_id="e-0001", group_id="g-0001",
                    actor_user="u-alice", actor_role="member", action="job.cancel",
                    resource_uri="job/abc", decision="allow", override=False, reason="", metadata={})
    key = w.write(ev)
    body = minio_s3.get_object(Bucket=minio_bucket, Key=key)["Body"].read().decode()
    assert json.loads(body)["action"] == "job.cancel"
