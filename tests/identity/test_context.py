# tests/identity/test_context.py
# 身份降两级(平台→企业→用户):parse_context 读 token 的 organization claim(org alias 数组),
# Membership 去 group_id;角色由 realm role 表达(member / enterprise-admin)。
from libs.identity.context import parse_context, Context, Membership


def test_parse_org_claim_single():
    ctx = parse_context(sub="u-1", organization=["ent-demo"], realm_roles=[])
    assert ctx.memberships == [Membership(enterprise_id="ent-demo", role="member")]
    assert not hasattr(ctx.memberships[0], "group_id")  # group 维度已删


def test_parse_enterprise_admin_role():
    ctx = parse_context(sub="u-1", organization=["ent-demo"], realm_roles=["enterprise-admin"])
    assert ctx.memberships[0].role == "enterprise-admin"


def test_parse_multi_org():
    ctx = parse_context(sub="u-1", organization=["ent-demo", "ent-beta"], realm_roles=[])
    assert [m.enterprise_id for m in ctx.memberships] == ["ent-demo", "ent-beta"]
    assert all(m.role == "member" for m in ctx.memberships)


def test_parse_platform_admin():
    ctx = parse_context(sub="u-1", organization=[], realm_roles=["platform-admin"])
    assert ctx.is_platform_admin and ctx.memberships == []


def test_role_in_no_group_arg():
    ctx = parse_context(sub="u-1", organization=["ent-demo"], realm_roles=["enterprise-admin"])
    assert ctx.role_in("ent-demo") == "enterprise-admin"
    assert ctx.role_in("ent-other") is None


def test_parse_empty_org_no_memberships():
    ctx = parse_context(sub="u-1", organization=[], realm_roles=[])
    assert ctx == Context(user="u-1", memberships=[], is_platform_admin=False)
