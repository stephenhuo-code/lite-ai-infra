# libs/authz/engine.py
from __future__ import annotations
from libs.identity.context import Context
from libs.authz.types import Resource, Decision

def can(ctx: Context, action: str, resource: Resource) -> Decision:
    """v1 薄 PolicyEngine。授权的唯一出入口（宪法 §2.4）。owner 模型(ADR-024)。
    强制：认证(=有 ctx) + 企业硬隔离 + owner-only(owner==user 或 enterprise-admin)。
    GPU>4 配额门槛 = enterprise-admin。
    身份降两级(ADR-025):已无用户组层;group 访问(scope / 跨用户共享)属 v2(Cerbos)。"""
    # platform-admin 只能走 /admin/* 特权路径；普通业务路径不允许
    if ctx.is_platform_admin:
        return Decision(False, "platform-admin must use /admin/* privileged API")

    # 企业硬隔离(§1.6):ctx 无任一 membership 命中资源企业 → 跨企业 deny
    in_enterprise = any(m.enterprise_id == resource.enterprise_id for m in ctx.memberships)
    if not in_enterprise:
        return Decision(False, "cross-enterprise")

    ent_admin = any(m.enterprise_id == resource.enterprise_id and m.role == "enterprise-admin"
                    for m in ctx.memberships)

    # GPU 配额门槛(owner 模型:enterprise-admin)
    if action == "job.submit" and (resource.attrs or {}).get("gpu", 0) > 4 and not ent_admin:
        return Decision(False, "> 4 GPU job requires enterprise-admin")

    # 智能体库(ADR-027):建/改/删智能体须本企业 enterprise-admin。
    # agent 是企业共享资源(owner=None),故不能靠下方 owner-only 默认放行——显式门槛。
    if action in ("agent:create", "agent:configure", "agent:delete") and not ent_admin:
        return Decision(False, "agent create/configure/delete requires enterprise-admin")

    # owner-only(v1):owner 或 enterprise-admin;group 访问/跨用户共享 → Cerbos v2。
    # owner=None(资源无主,如 S0 stub 解析不出 owner)放行本企业成员——企业隔离已强制。
    is_owner = resource.owner in (None, ctx.user)
    if not (is_owner or ent_admin):
        return Decision(False, "owner / enterprise-admin only (group sharing → Cerbos v-next)")

    return Decision(True, "")
