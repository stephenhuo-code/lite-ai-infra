# services/gateway/bff/omnigent_proxy.py
# BFF 反代 omnigent(Plan 9a · Task T4):通用对话反代,无数据访问。
# 身份取自【已认证 BFF 会话】(request.state.bearer → claims → email),经 X-Forwarded-Email 注入下游;
# 客户端伪造的 X-Forwarded-Email 绝不转发(每次都新建到 omnigent 的请求,不透传客户端任何头)——
# BFF 是唯一信任边界(omnigent 跑在 header-trust,信任 X-Forwarded-Email)。
# header-trust 红线:omnigent 不可被客户端直达 + BFF 必须剥伪造头。9a 无 MCP/承重墙/catalog/file/term。
from __future__ import annotations

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from libs.identity.context import parse_context
from services._scaffold.auth import _as_list

# claude-native-ui 默认 agent(探针 live-pinned);前端通常显式从 /v1/ws/agents 选,缺省时回退此。
DEFAULT_AGENT_ID = "ag_58a1bc5bf0bba6d31ceeb7661f8d751c"
_IDENTITY_HEADER = "X-Forwarded-Email"


def _resolve(request: Request, claims):
    """从【已认证会话】解出 email;未认证/坏 token → (None, JSONResponse 401)。
    身份只来自会话内 access token 的 claims —— 绝不信任请求头/体(C-1 / 反伪造命门)。"""
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
    email = c.get("email") or c.get("preferred_username") or ctx.user
    return email, None


def make_omnigent_router(*, claims, omni_base_url: str = "http://omnigent:8000",
                         send_identity: bool = True,
                         transport: httpx.BaseTransport | None = None) -> APIRouter:
    """omnigent 反代路由(全在 /v1/ws/* 下,受会话中间件保护 + CSRF)。
    transport:测试注入 httpx.MockTransport;send_identity=False 时不发身份头(dev 单用户)。"""
    base = omni_base_url.rstrip("/")
    router = APIRouter()

    def _headers(email: str) -> dict:
        # 每次都新建头集合 —— 绝不复用/转发客户端的头(伪造的 X-Forwarded-Email 因此到不了 omnigent)。
        h = {"Accept": "application/json"}
        if send_identity:
            h[_IDENTITY_HEADER] = email
        return h

    def _client() -> httpx.Client:
        # trust_env=False:连 localhost/容器内 omnigent 不走代理(SOCKS 代理会断连)。
        return httpx.Client(base_url=base, timeout=30, trust_env=False, transport=transport)

    def _passthru(r: httpx.Response) -> JSONResponse:
        try:
            content = r.json()
        except Exception:
            content = {"raw": r.text}
        return JSONResponse(status_code=r.status_code, content=content)

    @router.get("/v1/ws/agents")
    def agents(request: Request):
        email, err = _resolve(request, claims)
        if err:
            return err
        with _client() as cli:
            return _passthru(cli.get("/v1/agents", headers=_headers(email)))

    @router.get("/v1/ws/sessions")
    def list_sessions(request: Request):
        # omnigent 已按 X-Forwarded-Email owner-filter,故只回当前用户自己的会话。
        email, err = _resolve(request, claims)
        if err:
            return err
        with _client() as cli:
            return _passthru(cli.get("/v1/sessions", headers=_headers(email)))

    @router.post("/v1/ws/sessions")
    async def create_session(request: Request):
        # managed 建会话:JSON {agent_id, host_type:"managed"}(红线:绝不 multipart,绝不 host_id)。
        email, err = _resolve(request, claims)
        if err:
            return err
        try:
            body = await request.json()
        except Exception:
            body = {}
        agent_id = (body or {}).get("agent_id") or DEFAULT_AGENT_ID
        payload = {"agent_id": agent_id, "host_type": "managed"}
        with _client() as cli:
            return _passthru(cli.post("/v1/sessions", json=payload, headers=_headers(email)))

    @router.post("/v1/ws/sessions/{session_id}/turn")
    async def turn(session_id: str, request: Request):
        email, err = _resolve(request, claims)
        if err:
            return err
        try:
            body = await request.json()
        except Exception:
            body = {}
        text = (body or {}).get("text", "")
        event = {"type": "message",
                 "data": {"role": "user", "content": [{"type": "text", "text": text}]}}
        with _client() as cli:
            return _passthru(cli.post(f"/v1/sessions/{session_id}/events", json=event,
                                      headers=_headers(email)))

    @router.get("/v1/ws/sessions/{session_id}/items")
    def items(session_id: str, request: Request):
        email, err = _resolve(request, claims)
        if err:
            return err
        with _client() as cli:
            return _passthru(cli.get(f"/v1/sessions/{session_id}/items",
                                     params={"order": "asc"}, headers=_headers(email)))

    @router.get("/v1/ws/sessions/{session_id}/stream")
    async def stream(session_id: str, request: Request):
        # SSE 透传:转发所有上游字节,绝不在 response.completed 处终止(deltas 在 completed 之后才到)。
        email, err = _resolve(request, claims)
        if err:
            return err
        url = f"{base}/v1/sessions/{session_id}/stream"
        headers = {"Accept": "text/event-stream"}
        if send_identity:
            headers[_IDENTITY_HEADER] = email

        async def gen():
            async with httpx.AsyncClient(timeout=None, trust_env=False,
                                         transport=transport) as ac:
                async with ac.stream("GET", url, headers=headers) as r:
                    async for chunk in r.aiter_raw():
                        yield chunk

        return StreamingResponse(gen(), media_type="text/event-stream")

    return router
