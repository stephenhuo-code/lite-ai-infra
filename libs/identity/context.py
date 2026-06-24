# libs/identity/context.py
# 身份降两级(平台 → 企业 → 用户;ADR-025):token 仅认证,带 organization claim(KC Organization
# Membership mapper = org alias 数组,见 spike RESULTS F1/F2)。parse_context 据此产出 Membership
# (enterprise_id = org alias,去 group_id);角色经 realm role 表达(member / enterprise-admin),
# 随 token 带出(v1 单企业够用;多企业 per-org 角色 = vN+)。授权决策仍唯一经 can()。
from __future__ import annotations

from dataclasses import dataclass, field

from libs.identity.ids import EnterpriseId

_PLATFORM_ROLE = "platform-admin"
_ENT_ADMIN_ROLE = "enterprise-admin"


@dataclass(frozen=True)
class Membership:
    enterprise_id: EnterpriseId
    role: str  # member | enterprise-admin


@dataclass(frozen=True)
class Context:
    user: str
    memberships: list[Membership] = field(default_factory=list)
    is_platform_admin: bool = False

    def role_in(self, enterprise_id: EnterpriseId) -> str | None:
        """该用户在指定企业的角色;非成员 → None。enterprise-admin 优先于 member。"""
        best = None
        for m in self.memberships:
            if m.enterprise_id != enterprise_id:
                continue
            if m.role == _ENT_ADMIN_ROLE:
                return _ENT_ADMIN_ROLE
            best = best or m.role
        return best


def parse_context(sub: str, organization: list[str], realm_roles: list[str]) -> Context:
    """从 token claim 构 Context。organization = org alias 列表(KC multivalued mapper)。
    role 暂用 realm role 全局判(v1 单企业够用;多企业 per-org 角色 = vN+)。"""
    roles = realm_roles or []
    is_platform = _PLATFORM_ROLE in roles
    role = _ENT_ADMIN_ROLE if _ENT_ADMIN_ROLE in roles else "member"
    memberships = [Membership(EnterpriseId(a), role) for a in (organization or [])]
    return Context(user=sub, memberships=memberships, is_platform_admin=is_platform)
