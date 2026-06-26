# services/dev_workspace_mcp/tools/register.py
# 注册产物回 catalog:复用 catalog-driven(ADR-023)语义——processed location 必须落本人
# processed/ 前缀(owner 模型),owner=ctx.user;越界前缀 fail-closed。meta 为注入的注册客户端。
from __future__ import annotations

from libs.identity.context import Context
from services._scaffold.auth import enterprise_of


def register_processed(ctx: Context, meta, *, name: str, location: str,
                       derived_from: str, fmt: str = "lance") -> dict:
    ent = enterprise_of(ctx)
    allowed = f"s3://lite-ai/{ent}/{ctx.user}/processed/"   # 与 metadata_service 同前缀语义
    if not location.startswith(allowed):
        return {"error": "forbidden"}                       # 越界前缀
    return meta.create(name=name, location=location, owner=ctx.user, enterprise=ent,
                       kind="processed", format=fmt, derived_from=derived_from, scope="private")
