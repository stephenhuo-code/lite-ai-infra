# tests/authz/test_can.py
import pytest
from libs.identity.context import parse_context
from libs.authz.types import Resource
from libs.authz.engine import can

def ctx(groups, sub="u-alice"):
    return parse_context(sub=sub, groups=groups)

ALICE = ["/e-0001/g-0001/members"]
LEAD  = ["/e-0001/g-0001/admins"]
PADM  = ["/platform-admins"]
JOB = lambda **k: Resource(kind="job", enterprise_id="e-0001", group_id="g-0001", **k)

@pytest.mark.parametrize("name,context,action,resource,expect_allow,reason_sub", [
  ("AC-1",  ctx(ALICE), "job.delete", JOB(owner="u-alice", attrs={"state":"running"}), True, ""),
  ("AC-2",  ctx(ALICE), "job.delete", JOB(owner="u-bob", attrs={"state":"running"}), False, "owner"),
  ("AC-4",  ctx(ALICE), "job.submit", JOB(attrs={"gpu":4}), True, ""),
  ("AC-5",  ctx(ALICE), "job.submit", JOB(attrs={"gpu":8}), False, "group-admin"),
  ("AC-6",  ctx(ALICE), "dataset.read", Resource(kind="dataset", enterprise_id="e-0099"), False, "cross-enterprise"),
  ("AC-9",  ctx(LEAD),  "job.delete", JOB(owner="u-bob", attrs={"state":"running"}), True, ""),
  ("AC-10", ctx(LEAD),  "job.submit", JOB(attrs={"gpu":8}), True, ""),
  ("AC-15", ctx(PADM),  "job.delete", Resource(kind="job", enterprise_id="e-0099", owner="x"), False, "admin"),
])
def test_can_v1_matrix(name, context, action, resource, expect_allow, reason_sub):
    d = can(context, action, resource)
    assert d.allow is expect_allow, f"{name}: {d.reason}"
    assert reason_sub in d.reason
