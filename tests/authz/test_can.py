# tests/authz/test_can.py
# owner 模型(ADR-024)+ 身份降两级(ADR-025):企业硬隔离 + owner-only;无用户组层。
import pytest
from libs.identity.context import parse_context
from libs.authz.types import Resource
from libs.authz.engine import can

def ctx(spec, sub="u-alice"):
    organization, realm_roles = spec
    return parse_context(sub=sub, organization=list(organization), realm_roles=list(realm_roles))

# 企业归属来自 organization claim(org alias);角色经 realm role(member / enterprise-admin)。
ALICE  = (["e-0001"], [])                    # 普通成员
EADMIN = (["e-0001"], ["enterprise-admin"])  # 企业管理员
PADM   = ([], ["platform-admin"])            # 平台管理员(无企业)
JOB = lambda **k: Resource(kind="job", enterprise_id="e-0001", **k)
DATASET = lambda **k: Resource(kind="dataset", enterprise_id="e-0001", **k)
AGENT = lambda **k: Resource(kind="agent", enterprise_id="e-0001", **k)

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
  # platform-admin 调 agent:create → deny(is_platform_admin 早返回先于 agent 规则;
  # 证明 agent 规则永不被 platform-admin 触达,建智能体须企业 enterprise-admin 走 /admin/* 之外业务路径)
  ("PADM-AGENT-CREATE", ctx(PADM), "agent:create", AGENT(owner=None), False, "/admin/*"),

  # 智能体库(ADR-027):create/configure/delete 须 enterprise-admin(企业共享资源 owner=None)
  ("AGENT-CREATE-MEMBER-DENY", ctx(ALICE),  "agent:create",    AGENT(owner=None), False, "enterprise-admin"),
  ("AGENT-CREATE-EADM-OK",     ctx(EADMIN), "agent:create",    AGENT(owner=None), True,  ""),
  ("AGENT-CONFIG-MEMBER-DENY", ctx(ALICE),  "agent:configure", AGENT(owner=None), False, "enterprise-admin"),
  ("AGENT-CONFIG-EADM-OK",     ctx(EADMIN), "agent:configure", AGENT(owner=None), True,  ""),
  ("AGENT-DELETE-MEMBER-DENY", ctx(ALICE),  "agent:delete",    AGENT(owner=None), False, "enterprise-admin"),
  ("AGENT-DELETE-EADM-OK",     ctx(EADMIN), "agent:delete",    AGENT(owner=None), True,  ""),
  # 跨企业:e-0001 的 enterprise-admin 对 e-0002 的 agent → 仍 deny(企业硬隔离先于角色门)
  ("AGENT-CREATE-XENT", ctx(EADMIN), "agent:create", Resource(kind="agent", enterprise_id="e-0002", owner=None), False, "cross-enterprise"),
])
def test_can_owner_matrix(name, context, action, resource, expect_allow, reason_sub):
    d = can(context, action, resource)
    assert d.allow is expect_allow, f"{name}: {d.reason}"
    assert reason_sub in d.reason, f"{name}: reason={d.reason!r}"
