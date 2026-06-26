# services/dev_workspace_mcp/app.py
# http-transport MCP server。URL 形如 /s/<token>/mcp;包裹层把 token 注入 contextvar(身份绑定,
# Task0 实证:omnigent 按注册 URL 原样连、令牌随 URL 抵达),再交给 FastMCP ASGI app。
# 工具调用前置 can()(数据授权唯一出入口,宪法 §2.4)。工具对 agent 显示为 {server}__{tool}
# (Task0:本 server 名 liteai → 如 liteai__whoami)。
from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

from services.dev_workspace_mcp.identity import current_context, set_current_token
from services.dev_workspace_mcp.tools.catalog import read_schema as _read_schema
from services.gateway.bff.wstoken import WorkspaceTokenStore
from services.metadata_service.gravitino import GravitinoClient

STORE = WorkspaceTokenStore(ttl_seconds=int(os.getenv("WS_TOKEN_TTL", "3600")))
mcp = FastMCP("liteai")

_GRAVITINO: GravitinoClient | None = None


def _gravitino() -> GravitinoClient:
    # 进程生命周期单例(httpx 连接池),与 metadata_service 同 env。
    global _GRAVITINO
    if _GRAVITINO is None:
        _GRAVITINO = GravitinoClient(base_url=os.environ.get("GRAVITINO_URL", "http://localhost:8091"))
    return _GRAVITINO


@mcp.tool()
def whoami() -> dict:
    """探活 + 身份回显:证明令牌已绑定为某用户/企业。"""
    ctx = current_context()
    if ctx is None:
        return {"error": "unauthenticated"}        # fail-closed
    ent = ctx.memberships[0].enterprise_id if ctx.memberships else None
    return {"user": ctx.user, "enterprise": str(ent) if ent else None}


@mcp.tool()
def catalog_read_schema(dataset: str, catalog: str = "data", schema: str = "datasets") -> dict:
    """探查数据集:返回 owner/scope/format/kind/num_samples/location(经 can() 把关)。
    对 agent 显示为 liteai__catalog_read_schema。"""
    ctx = current_context()
    if ctx is None:
        return {"error": "unauthenticated"}
    return _read_schema(ctx, _gravitino(), dataset=dataset, catalog=catalog, schema=schema)


def build_asgi(store: WorkspaceTokenStore = STORE):
    inner = mcp.streamable_http_app()

    async def app(scope, receive, send):
        if scope["type"] == "http":
            parts = scope.get("path", "").split("/")
            if len(parts) > 2 and parts[1] == "s":
                set_current_token(store, parts[2])
                scope = dict(scope)
                scope["path"] = "/" + "/".join(parts[3:])
        await inner(scope, receive, send)

    return app


asgi = build_asgi()
