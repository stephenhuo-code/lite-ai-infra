# libs/authz/engine.py
from __future__ import annotations
from libs.identity.context import Context
from libs.authz.types import Resource, Decision

_ROLE_RANK = {"member": 0, "group-admin": 1, "enterprise-admin": 2}

def can(ctx: Context, action: str, resource: Resource) -> Decision:
    """v1 薄 PolicyEngine。授权的唯一出入口（宪法 §2.4）。
    强制：认证(=有 ctx) + 企业隔离 + owner + 角色门槛。
    用户组 scope / 共享 / 派生规则属 v2（Cerbos）——can() 签名不变。"""
    # platform-admin 只能走 /admin/* 特权路径；普通业务路径仍按企业隔离
    if ctx.is_platform_admin:
        return Decision(False, "platform-admin must use /admin/* privileged API")

    role = ctx.role_in(resource.enterprise_id, resource.group_id)
    if role is None:  # AC-6/13/26：硬企业隔离
        in_enterprise = any(m.enterprise_id == resource.enterprise_id for m in ctx.memberships)
        return Decision(False, "cross-group" if in_enterprise else "cross-enterprise")

    rank = _ROLE_RANK[role]
    # 角色门槛：大 GPU 作业需 group-admin+
    if action == "job.submit" and (resource.attrs or {}).get("gpu", 0) > 4 and rank < 1:
        return Decision(False, "> 4 GPU job requires group-admin+")
    # mutation 的 owner 检查。owner=None(资源无主,如 S0 stub 解析不出 owner)时
    # 有意放行任何本组成员——企业/组隔离已在上面强制;owner 细化随真实资源查找落地(vN+)。
    if action.endswith((".delete", ".cancel", ".update")) and resource.owner not in (None, ctx.user):
        if rank < 1:
            return Decision(False, "only owner / group-admin / enterprise-admin")
    return Decision(True, "")
