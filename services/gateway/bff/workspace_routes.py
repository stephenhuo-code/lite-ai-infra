# services/gateway/bff/workspace_routes.py
# BFF HTTP 路由:建工作区会话。身份取自【已认证 BFF 会话】(request.state.bearer → claims →
# parse_context),绝不信任请求体的身份。镜像 middleware /auth/me 的取身份模式。
# create_workspace_session 内部铸令牌 + 注册我们的 MCP server(地基)。
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from libs.identity.context import parse_context
from libs.identity.ids import EnterpriseId
from services._scaffold.auth import enterprise_of
from services.gateway.bff.middleware import _as_list
from services.gateway.bff.workspace import create_workspace_session


def _claim_org_roles(c: dict):
    return _as_list(c.get("organization")), (c.get("realm_access") or {}).get("roles", [])


def make_workspace_router(*, claims, store, omni_factory, mcp_base_url: str,
                          agent_id: str = "liteai_devws") -> APIRouter:
    router = APIRouter()

    @router.post("/v1/ws/sessions")
    def create(request: Request):
        sd = getattr(request.state, "session", None)
        bearer = getattr(request.state, "bearer", None)
        if sd is None or not bearer:
            return JSONResponse(status_code=401, content={"reason": "unauthenticated"})
        try:
            c = claims(bearer)
        except Exception:
            return JSONResponse(status_code=401, content={"reason": "invalid token"})
        organization, realm_roles = _claim_org_roles(c)
        ctx = parse_context(sub=c["sub"], organization=organization, realm_roles=realm_roles)
        try:
            enterprise = enterprise_of(ctx)
        except HTTPException as e:
            return JSONResponse(status_code=e.status_code, content={"reason": e.detail})
        role = ctx.role_in(EnterpriseId(enterprise)) or "member"
        email = c.get("email") or ctx.user
        return create_workspace_session(
            sub=ctx.user, enterprise=enterprise, role=role, agent_id=agent_id,
            store=store, omni=omni_factory(email), mcp_base_url=mcp_base_url)

    return router
