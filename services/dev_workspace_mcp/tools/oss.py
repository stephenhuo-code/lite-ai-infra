# services/dev_workspace_mcp/tools/oss.py
# OSS 读取工具:仅限调用者「企业/owner」前缀(owner 模型 ADR-024),越界 fail-closed。
# 路径隔离在触达存储前完成(与 metadata_service register 的 allowed 前缀同语义)。
from __future__ import annotations

from libs.identity.context import Context
from services._scaffold.auth import enterprise_of


def allowed_prefix(ctx: Context) -> str:
    return f"{enterprise_of(ctx)}/{ctx.user}/"


def oss_read(ctx: Context, oss, *, path: str) -> dict:
    if not path.startswith(allowed_prefix(ctx)):
        return {"error": "forbidden"}          # 越界,不触达存储
    blob = oss.get(path)
    return {"path": path, "bytes_len": len(blob)}


def oss_list(ctx: Context, oss, *, prefix: str = "") -> dict:
    base = allowed_prefix(ctx)
    full = base + prefix.lstrip("/")
    if not full.startswith(base):
        return {"error": "forbidden"}
    return {"prefix": full, "keys": list(oss.list(full))}
