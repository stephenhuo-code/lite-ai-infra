# libs/identity/context.py
from __future__ import annotations
import re
from dataclasses import dataclass, field

from libs.identity.ids import EnterpriseId, GroupId

_RE_GROUP = re.compile(r"^/(?P<eid>e-[0-9a-z]+)/(?P<gid>g-[0-9a-z]+)/(?P<sub>admins|members)$")
_RE_ENT_ADMIN = re.compile(r"^/(?P<eid>e-[0-9a-z]+)/admins$")
_PLATFORM = "/platform-admins"
_ROLE = {"admins": "group-admin", "members": "member"}

@dataclass(frozen=True)
class Membership:
    enterprise_id: EnterpriseId
    group_id: GroupId | None
    role: str  # member | group-admin | enterprise-admin

@dataclass(frozen=True)
class Context:
    user: str
    memberships: list[Membership] = field(default_factory=list)
    is_platform_admin: bool = False

    def role_in(self, enterprise_id: EnterpriseId, group_id: GroupId | None = None) -> str | None:
        best = None
        for m in self.memberships:
            if m.enterprise_id != enterprise_id:
                continue
            if m.role == "enterprise-admin":
                best = "enterprise-admin"
            elif m.group_id == group_id and best != "enterprise-admin":
                best = m.role
        return best

def parse_context(sub: str, groups: list[str]) -> Context:
    memberships: list[Membership] = []
    is_platform = False
    for g in groups or []:
        if g == _PLATFORM:
            is_platform = True
            continue
        if (m := _RE_GROUP.match(g)):
            memberships.append(Membership(EnterpriseId(m["eid"]), GroupId(m["gid"]), _ROLE[m["sub"]]))
        elif (m := _RE_ENT_ADMIN.match(g)):
            memberships.append(Membership(EnterpriseId(m["eid"]), None, "enterprise-admin"))
    return Context(user=sub, memberships=memberships, is_platform_admin=is_platform)
