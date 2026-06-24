# tests/authz/test_can.py
# owner 模型(ADR-024):企业硬隔离 + owner-only;group 不参与 can() 决策。
import pytest
from libs.identity.context import parse_context
from libs.authz.types import Resource
from libs.authz.engine import can

def ctx(groups, sub="u-alice"):
    return parse_context(sub=sub, groups=groups)

# alice/bob 同企业 e-0001 同组 g-0001(组在 owner 模型下不再影响 can 决策)
ALICE  = ["/e-0001/g-0001/members"]
EADMIN = ["/e-0001/admins"]          # 企业管理员(enterprise-admin)
PADM   = ["/platform-admins"]
JOB = lambda **k: Resource(kind="job", enterprise_id="e-0001", group_id="g-0001", **k)
DATASET = lambda **k: Resource(kind="dataset", enterprise_id="e-0001", group_id="g-0001", **k)

@pytest.mark.parametrize("name,context,action,resource,expect_allow,reason_sub", [
  # 企业硬隔离:alice(e-0001) 访 e-0002 资源 → deny
  ("ENT-ISO",   ctx(ALICE),  "dataset.read",   Resource(kind="dataset", enterprise_id="e-0002", owner="u-alice"), False, "cross-enterprise"),

  # owner-only(read):自己的 dataset → allow;同企业他人(bob)的 → deny
  ("OWN-READ",  ctx(ALICE),  "dataset.read",   DATASET(owner="u-alice"), True,  ""),
  ("OTHER-READ",ctx(ALICE),  "dataset.read",   DATASET(owner="u-bob"),   False, "owner"),

  # owner mutation:删自己 job → allow;删 bob 的 → deny
  ("OWN-DEL",   ctx(ALICE),  "job.delete",     JOB(owner="u-alice", attrs={"state":"running"}), True,  ""),
  ("OTHER-DEL", ctx(ALICE),  "job.delete",     JOB(owner="u-bob",   attrs={"state":"running"}), False, "owner"),

  # enterprise-admin:本企业任意 owner 的资源 → allow
  ("EADM-OTHER",ctx(EADMIN), "dataset.read",   DATASET(owner="u-bob"),   True,  ""),
  ("EADM-DEL",  ctx(EADMIN), "job.delete",     JOB(owner="u-bob", attrs={"state":"running"}), True,  ""),
  # enterprise-admin 跨企业仍 deny
  ("EADM-XENT", ctx(EADMIN), "dataset.read",   Resource(kind="dataset", enterprise_id="e-0002", owner="u-bob"), False, "cross-enterprise"),

  # GPU 配额:member 提 >4 GPU → deny(门槛 enterprise-admin);<=4 → allow
  ("GPU-OK",    ctx(ALICE),  "job.submit",     JOB(owner="u-alice", attrs={"gpu":4}), True,  ""),
  ("GPU-DENY",  ctx(ALICE),  "job.submit",     JOB(owner="u-alice", attrs={"gpu":8}), False, "enterprise-admin"),
  ("GPU-EADM",  ctx(EADMIN), "job.submit",     JOB(owner="u-bob",   attrs={"gpu":8}), True,  ""),

  # platform-admin 走业务路径 → deny(必须 /admin/*)
  ("PADM-BIZ",  ctx(PADM),   "job.delete",     Resource(kind="job", enterprise_id="e-0001", owner="x"), False, "admin"),
])
def test_can_owner_matrix(name, context, action, resource, expect_allow, reason_sub):
    d = can(context, action, resource)
    assert d.allow is expect_allow, f"{name}: {d.reason}"
    assert reason_sub in d.reason, f"{name}: reason={d.reason!r}"
