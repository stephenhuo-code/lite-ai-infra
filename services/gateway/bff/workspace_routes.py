# services/gateway/bff/workspace_routes.py
# BFF HTTP 路由(Dev Workspace,plan 9b):建会话 / 发 turn / SSE 对话流透传。
# 身份取自【已认证 BFF 会话】(request.state.bearer → claims → parse_context),绝不信任请求体。
# turn=POST /events、stream=SSE 透传(探针 RESULTS 9b)。前端不持 token,全经此反代。
from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from libs.identity.context import parse_context
from libs.identity.ids import EnterpriseId
from services._scaffold.auth import enterprise_of
from services.gateway.bff.middleware import _as_list
from services.gateway.bff.omnigent_client import items_to_chat, user_message_event
from services.gateway.bff.workspace import create_workspace_session


def _resolve(request: Request, claims):
    """从会话解出 (ctx, enterprise, role, email);未认证/无企业 → (None, JSONResponse)。"""
    sd = getattr(request.state, "session", None)
    bearer = getattr(request.state, "bearer", None)
    if sd is None or not bearer:
        return None, JSONResponse(status_code=401, content={"reason": "unauthenticated"})
    try:
        c = claims(bearer)
    except Exception:
        return None, JSONResponse(status_code=401, content={"reason": "invalid token"})
    ctx = parse_context(sub=c["sub"], organization=_as_list(c.get("organization")),
                        realm_roles=(c.get("realm_access") or {}).get("roles", []))
    try:
        enterprise = enterprise_of(ctx)
    except HTTPException as e:
        return None, JSONResponse(status_code=e.status_code, content={"reason": e.detail})
    role = ctx.role_in(EnterpriseId(enterprise)) or "member"
    email = c.get("email") or ctx.user
    return (ctx, enterprise, role, email), None


def make_workspace_router(*, claims, store, omni_factory, mcp_base_url: str,
                          agent_config_yaml: str, send_identity: bool = True,
                          omni_base_url: str = "http://omnigent:8000") -> APIRouter:
    router = APIRouter()

    @router.post("/v1/ws/sessions")
    def create(request: Request):
        ident, err = _resolve(request, claims)
        if err:
            return err
        ctx, enterprise, role, email = ident
        return create_workspace_session(
            sub=ctx.user, enterprise=enterprise, role=role, agent_config_yaml=agent_config_yaml,
            store=store, omni=omni_factory(email), mcp_base_url=mcp_base_url)

    @router.post("/v1/ws/sessions/{session_id}/turn")
    async def turn(session_id: str, request: Request):
        ident, err = _resolve(request, claims)
        if err:
            return err
        _, _, _, email = ident
        body = await request.json()
        text = (body or {}).get("text", "")
        return omni_factory(email).post_event(session_id, user_message_event(text))

    @router.get("/v1/ws/sessions/{session_id}/items")
    def items(session_id: str, request: Request):
        # 对话历史(claude-native 回复只在 items;前端以此为准,stream 仅作刷新触发)。
        ident, err = _resolve(request, claims)
        if err:
            return err
        _, _, _, email = ident
        return {"items": items_to_chat(omni_factory(email).get_items(session_id))}

    @router.post("/v1/ws/sessions/{session_id}/elicitations/{eid}/resolve")
    async def resolve(session_id: str, eid: str, request: Request):
        ident, err = _resolve(request, claims)
        if err:
            return err
        _, _, _, email = ident
        body = await request.json()
        return omni_factory(email).resolve_elicitation(session_id, eid, bool((body or {}).get("approve")))

    @router.get("/v1/ws/sessions/{session_id}/stream")
    async def stream(session_id: str, request: Request):
        ident, err = _resolve(request, claims)
        if err:
            return err
        _, _, _, email = ident

        async def gen():
            url = f"{omni_base_url.rstrip('/')}/v1/sessions/{session_id}/stream"
            headers = {"Accept": "text/event-stream"}
            if send_identity:                          # dev 单用户:不发身份头(与会话 owner=local 对齐)
                headers["X-Forwarded-Email"] = email
            async with httpx.AsyncClient(timeout=None, trust_env=False) as ac:   # 不走代理
                async with ac.stream("GET", url, headers=headers) as r:
                    async for chunk in r.aiter_raw():
                        yield chunk

        return StreamingResponse(gen(), media_type="text/event-stream")

    return router
