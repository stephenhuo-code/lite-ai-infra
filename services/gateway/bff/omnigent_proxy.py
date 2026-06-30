# services/gateway/bff/omnigent_proxy.py
# BFF 反代 omnigent(Plan 9a · Task T4):通用对话反代,无数据访问。
# 身份取自【已认证 BFF 会话】(request.state.bearer → claims → email),经 X-Forwarded-Email 注入下游;
# 客户端伪造的 X-Forwarded-Email 绝不转发(每次都新建到 omnigent 的请求,不透传客户端任何头)——
# BFF 是唯一信任边界(omnigent 跑在 header-trust,信任 X-Forwarded-Email)。
# header-trust 红线:omnigent 不可被客户端直达 + BFF 必须剥伪造头。9a 无 MCP/承重墙/catalog/file/term。
from __future__ import annotations

import io
import tarfile
from datetime import datetime, timezone

import httpx
import yaml
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from libs.audit.oss_audit import AuditEvent, AuditWriter
from libs.authz.engine import can
from libs.authz.types import Resource
from libs.identity.context import Context, parse_context
from libs.identity.ids import EnterpriseId
from services._scaffold.auth import _as_list

# claude-native-ui 默认 agent(探针 live-pinned);前端通常显式从 /v1/ws/agents 选,缺省时回退此。
DEFAULT_AGENT_ID = "ag_58a1bc5bf0bba6d31ceeb7661f8d751c"
_IDENTITY_HEADER = "X-Forwarded-Email"

# 智能体库(ADR-027)企业归属前缀分隔符 = ASCII Unit Separator(U+001F)。
# omnigent agent name 是自由 str(fork 仅校验"安全字段集",不限 name 字符集 —— 实测
# third_party/omnigent .../builtin_agents.py 只在 name 缺失时 400)。U+001F 不可能出现在
# KC org alias 或用户展示名(均可打印)里 → 企业归属不可伪造、不会与展示名相撞。
# 不变量:有前缀 = 属该企业、仅该企业可见;无前缀 = 内置模板(全局共享)。
# 前缀只由 BFF 据已认证会话写入/解析/剥离,客户端从不发也不见。
_ENT_SEP = "\x1f"
# 仅 claude-native 系 harness 注入了全局共享订阅(ADR-027 §4);其余建出来不可用,先限于此。
_ALLOWED_HARNESSES = {"claude-native"}
_DEFAULT_HARNESS = "claude-native"


def _split_enterprise(name: str) -> tuple[str | None, str]:
    """解 omnigent agent name → (enterprise_alias|None, 展示名)。无前缀 = 内置(全局)。"""
    if _ENT_SEP in name:
        alias, _, display = name.partition(_ENT_SEP)
        return alias, display
    return None, name


def _visible_to(name: str, alias: str) -> bool:
    """该 agent(按 name 前缀)对 alias 企业是否可见:内置(无前缀)或前缀==alias。"""
    owner, _ = _split_enterprise(name)
    return owner is None or owner == alias


def _build_bundle_bytes(*, name: str, instructions: str | None, harness: str,
                        model: str | None, description: str | None) -> bytes:
    """搭只含【安全字段】的 .tar.gz(内含 config.yaml)。绝不写 mcp/env/auth/capability —
    fork 的安全白名单只允许 name/description/instructions/executor(type+harness)/llm.model。"""
    spec: dict = {
        "spec_version": 1,
        "name": name,
        "executor": {"type": "omnigent", "config": {"harness": harness}},
    }
    if description:
        spec["description"] = description
    if instructions:
        spec["instructions"] = instructions
    if model:
        spec["llm"] = {"model": model}
    cfg = yaml.safe_dump(spec, allow_unicode=True, sort_keys=False).encode("utf-8")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        info = tarfile.TarInfo(name="config.yaml")
        info.size = len(cfg)
        tf.addfile(info, io.BytesIO(cfg))
    return buf.getvalue()


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
    if not email:
        # fail closed:绝不把空 X-Forwarded-Email 发给 header-trust omnigent(身份歧义=拒绝)。
        return None, JSONResponse(status_code=401, content={"reason": "empty identity"})
    return email, None


def _resolve_ctx(request: Request, claims):
    """解【已认证会话】→ (email, ctx, 单企业 alias, None) 或 (None, None, None, err)。
    v1 单企业:0/多企业显式拒(不静默挑第一个,镜像 invite handler)。"""
    sd = getattr(request.state, "session", None)
    bearer = getattr(request.state, "bearer", None)
    if sd is None or not bearer:
        return None, None, None, JSONResponse(status_code=401, content={"reason": "unauthenticated"})
    try:
        c = claims(bearer)
    except Exception:
        return None, None, None, JSONResponse(status_code=401, content={"reason": "invalid token"})
    ctx = parse_context(sub=c["sub"], organization=_as_list(c.get("organization")),
                        realm_roles=(c.get("realm_access") or {}).get("roles", []))
    email = c.get("email") or c.get("preferred_username") or ctx.user
    if not email:
        return None, None, None, JSONResponse(status_code=401, content={"reason": "empty identity"})
    aliases: list[str] = []
    for m in ctx.memberships:
        if m.enterprise_id not in aliases:
            aliases.append(m.enterprise_id)
    if len(aliases) != 1:   # v1 单企业:0/多企业显式拒
        return None, None, None, JSONResponse(status_code=400,
                                              content={"reason": "ambiguous enterprise membership"})
    return email, ctx, aliases[0], None


def make_omnigent_router(*, claims, omni_base_url: str = "http://omnigent:8000",
                         send_identity: bool = True,
                         audit_writer: AuditWriter | None = None,
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

    def _call(fn) -> JSONResponse:
        # 包住到 omnigent 的一次 REST 调用:omnigent 不可达/传输失败(httpx.RequestError)
        # → 干净 502 + 明确 reason,而非未捕获 500(健壮性:失败显式,绝不静默卡死)。
        # 注:_passthru 仍保留上游非 2xx 原状态码 —— 只翻译"连不上/传输断"这一类。
        try:
            with _client() as cli:
                return _passthru(fn(cli))
        except httpx.RequestError:
            return JSONResponse(status_code=502, content={"reason": "omnigent unreachable"})

    def _fetch_agents_raw(email: str) -> list[dict] | JSONResponse:
        """拉 omnigent 全量 agent 列表(原始,含他企业);不可达 → 502。"""
        try:
            with _client() as cli:
                r = cli.get("/v1/agents", headers=_headers(email))
        except httpx.RequestError:
            return JSONResponse(status_code=502, content={"reason": "omnigent unreachable"})
        if r.status_code != 200:
            return JSONResponse(status_code=502,
                                content={"reason": "omnigent agents error", "status": r.status_code})
        try:
            body = r.json()
        except Exception:
            return JSONResponse(status_code=502, content={"reason": "omnigent bad response"})
        items = body.get("data") if isinstance(body, dict) else body
        return items if isinstance(items, list) else []

    def _audit_create(ctx: Context, alias: str, agent_id: str, display: str, harness: str) -> None:
        if audit_writer is None:
            return
        audit_writer.write(AuditEvent(
            ts=datetime.now(timezone.utc).isoformat(), enterprise_id=alias,
            actor_user=ctx.user, actor_role=ctx.role_in(EnterpriseId(alias)) or "none",
            action="agent:create", resource_uri=f"agent/{agent_id}", decision="allow",
            override=False, reason="", metadata={"name": display, "harness": harness}))

    @router.get("/v1/ws/agents")
    def agents(request: Request):
        # 列:omnigent 全量 → 按企业过滤(内置无前缀 + 本企业前缀)→ 剥前缀回干净展示名。
        email, ctx, alias, err = _resolve_ctx(request, claims)
        if err:
            return err
        raw = _fetch_agents_raw(email)
        if isinstance(raw, JSONResponse):
            return raw
        out = []
        for a in raw:
            name = a.get("name", "")
            if not _visible_to(name, alias):
                continue            # 他企业 agent → 不可见(隔离)
            owner, display = _split_enterprise(name)
            out.append({"id": a.get("id"), "name": display, "harness": a.get("harness"),
                        "description": a.get("description", ""),
                        "builtin": owner is None, "enterprise_owned": owner == alias})
        return JSONResponse(status_code=200, content={"data": out})

    @router.post("/v1/ws/agents")
    async def create_agent(request: Request):
        # 建:enterprise-admin(can())→ 搭安全 bundle(名带企业前缀)→ multipart POST omnigent → 审计。
        email, ctx, alias, err = _resolve_ctx(request, claims)
        if err:
            return err
        d = can(ctx, "agent:create", Resource(kind="agent", enterprise_id=EnterpriseId(alias),
                                              owner=None))
        if not d.allow:           # 非企业管理员 → 403,绝不打到 omnigent(can() 先于反代)
            return JSONResponse(status_code=403, content={"reason": d.reason})
        try:
            body = await request.json()
        except Exception:
            body = {}
        display = (body or {}).get("name", "").strip()
        if not display:
            return JSONResponse(status_code=400, content={"reason": "name required"})
        if _ENT_SEP in display:   # 客户端绝不能注入分隔符(防越界伪造前缀)
            return JSONResponse(status_code=400, content={"reason": "invalid name"})
        harness = ((body or {}).get("harness") or _DEFAULT_HARNESS).strip()
        if harness not in _ALLOWED_HARNESSES:   # 只允许已注入全局凭据的可用 harness
            return JSONResponse(status_code=400,
                                content={"reason": f"unsupported harness: {harness}"})
        instructions = (body or {}).get("instructions") or None
        model = ((body or {}).get("model") or "").strip() or None
        description = (body or {}).get("description") or None
        # 企业前缀来自【已认证会话】alias,绝非客户端输入 → 归属不可伪造。
        bundle = _build_bundle_bytes(name=f"{alias}{_ENT_SEP}{display}", instructions=instructions,
                                     harness=harness, model=model, description=description)
        files = {"bundle": ("bundle.tar.gz", bundle, "application/gzip")}
        try:
            with _client() as cli:
                r = cli.post("/v1/agents", files=files, headers=_headers(email))
        except httpx.RequestError:
            return JSONResponse(status_code=502, content={"reason": "omnigent unreachable"})
        if r.status_code >= 400:
            # 透传 omnigent 4xx(安全字段门 / 重名)为干净错误,不伪装成功。
            try:
                detail = r.json()
            except Exception:
                detail = {"raw": r.text}
            return JSONResponse(status_code=r.status_code if r.status_code < 500 else 502,
                                content={"reason": "create failed", "detail": detail})
        try:
            obj = r.json()
        except Exception:
            obj = {}
        agent_id = obj.get("id", "")
        _audit_create(ctx, alias, agent_id, display, harness)
        # 回前端:展示名剥前缀(前端永不见企业前缀)
        return JSONResponse(status_code=200, content={
            "id": agent_id, "name": display, "harness": obj.get("harness", harness),
            "description": obj.get("description", description or ""),
            "builtin": False, "enterprise_owned": True})

    @router.get("/v1/ws/sessions")
    def list_sessions(request: Request):
        # omnigent 已按 X-Forwarded-Email owner-filter,故只回当前用户自己的会话。
        email, err = _resolve(request, claims)
        if err:
            return err
        return _call(lambda cli: cli.get("/v1/sessions", headers=_headers(email)))

    @router.post("/v1/ws/sessions")
    async def create_session(request: Request):
        # managed 建会话:JSON {agent_id, host_type:"managed"}(红线:绝不 multipart,绝不 host_id)。
        # 隔离:建会话前校验 agent_id 属本企业或内置(防猜他企业 agent_id 建会话)。
        email, ctx, alias, err = _resolve_ctx(request, claims)
        if err:
            return err
        try:
            body = await request.json()
        except Exception:
            body = {}
        agent_id = (body or {}).get("agent_id") or DEFAULT_AGENT_ID
        # 拉全量 → 按 id 查 name → 校验归属(内置无前缀 或 前缀==本企业)。
        raw = _fetch_agents_raw(email)
        if isinstance(raw, JSONResponse):
            return raw
        match = next((a for a in raw if a.get("id") == agent_id), None)
        if match is None or not _visible_to(match.get("name", ""), alias):
            # 未知 / 他企业 agent_id → 拒(绝不创建 managed 会话)
            return JSONResponse(status_code=403, content={"reason": "agent not available"})
        payload = {"agent_id": agent_id, "host_type": "managed"}
        return _call(lambda cli: cli.post("/v1/sessions", json=payload, headers=_headers(email)))

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
        return _call(lambda cli: cli.post(f"/v1/sessions/{session_id}/events", json=event,
                                          headers=_headers(email)))

    @router.get("/v1/ws/sessions/{session_id}/items")
    def items(session_id: str, request: Request):
        email, err = _resolve(request, claims)
        if err:
            return err
        return _call(lambda cli: cli.get(f"/v1/sessions/{session_id}/items",
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

        # 在 commit 200 event-stream 之前先打开上游并检查状态 —— 否则上游不可达/非 2xx
        # 时客户端只会拿到一个断掉的 200 流(前端静默卡死)。健壮性:失败显式为真正的 JSON 502。
        ac = httpx.AsyncClient(timeout=None, trust_env=False, transport=transport)
        try:
            req = ac.build_request("GET", url, headers=headers)
            r = await ac.send(req, stream=True)
        except httpx.RequestError:
            await ac.aclose()
            return JSONResponse(status_code=502, content={"reason": "omnigent unreachable"})
        if r.status_code != 200:
            await r.aread()
            await r.aclose()
            await ac.aclose()
            return JSONResponse(status_code=502,
                                content={"reason": "omnigent stream error", "status": r.status_code})

        async def gen():
            try:
                async for chunk in r.aiter_raw():
                    yield chunk
            finally:
                await r.aclose()
                await ac.aclose()

        return StreamingResponse(gen(), media_type="text/event-stream")

    return router
