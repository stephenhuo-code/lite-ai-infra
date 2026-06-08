# tests/identity/test_context.py
import pytest
from libs.identity.context import parse_context, Context, Membership

def test_parse_member_single_group():
    ctx = parse_context(sub="u-alice", groups=["/e-0001/g-0001/members"])
    assert ctx == Context(user="u-alice",
                          memberships=[Membership("e-0001", "g-0001", "member")])

def test_parse_group_admin():
    ctx = parse_context(sub="u-lead", groups=["/e-0001/g-0001/admins"])
    assert ctx.memberships[0].role == "group-admin"

def test_parse_enterprise_admin_no_group():
    ctx = parse_context(sub="u-ea", groups=["/e-0001/admins"])
    assert ctx.memberships[0] == Membership("e-0001", None, "enterprise-admin")

def test_parse_platform_admin():
    ctx = parse_context(sub="u-p", groups=["/platform-admins"])
    assert ctx.is_platform_admin is True

def test_role_in_resolves_active_membership():
    ctx = parse_context(sub="u-x",
                        groups=["/e-0001/g-0001/admins", "/e-0001/g-0002/members"])
    assert ctx.role_in("e-0001", "g-0001") == "group-admin"
    assert ctx.role_in("e-0001", "g-0002") == "member"
    assert ctx.role_in("e-0099", "g-0001") is None

def test_ignores_unparseable_groups():
    ctx = parse_context(sub="u", groups=["/garbage", "/e-0001/g-0001/members"])
    assert len(ctx.memberships) == 1
