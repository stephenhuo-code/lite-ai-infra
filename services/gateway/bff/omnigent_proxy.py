# services/gateway/bff/omnigent_proxy.py
# BFF 反代 omnigent(Plan 9a · Task T4):通用对话反代,无数据访问。
# 身份取自【已认证 BFF 会话】(request.state.bearer → claims → email),经 X-Forwarded-Email 注入下游;
# 客户端伪造的 X-Forwarded-Email 绝不转发(每次都新建到 omnigent 的请求,不透传客户端任何头)——
# BFF 是唯一信任边界(omnigent 跑在 header-trust,信任 X-Forwarded-Email)。
# header-trust 红线:omnigent 不可被客户端直达 + BFF 必须剥伪造头。9a 无 MCP/承重墙/catalog/file/term。
from __future__ import annotations

import io
import re
import secrets
import tarfile
import unicodedata
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

# 智能体库(ADR-027)企业归属前缀分隔符 = ASCII 下划线("_")。
# 实测(third_party/omnigent .../spec/validator.py:16):omnigent agent name **不是**自由 str,
# 必须匹配 ^[a-zA-Z0-9_-]+$(无点/斜杠/空白/控制符/非 ASCII)。故旧的 U+001F(控制符)
# 会被 omnigent 400 拒(invalid_input);而企业展示名(可含中文)也根本进不了 name 字段。
# 因此本 BFF:
#   - name = "<alias>_<ascii-slug>"(仅承载【企业归属】+ 一个人类可读 ASCII 标识),
#   - 人类展示名(任意 Unicode)落 description 字段(实测 description 原样 round-trip)。
# "_" 选作分隔符的理由(round-trip 实测验证):
#   (a) YAML/omnigent name 校验全允许(可打印 ASCII,非控制符);
#   (b) KC org alias 形如 ent-demo / ent-<random>(ASCII 字母数字 + 连字符,**绝不含 "_"**)
#       → partition("_")[0] 必精确还原 alias,归属不可伪造;
#   (c) omnigent 内置模板名(debby/polly/*-native-ui/live-safe-helper…)用连字符,**绝不含 "_"**
#       → 无前缀(无 "_")= 内置(全局共享),不会把内置误判成某企业所有。
# 不变量:有前缀("_" 分隔)= 属该企业、仅该企业可见;无前缀 = 内置模板(全局共享)。
# 前缀只由 BFF 据已认证会话写入/解析/剥离,客户端从不发也不见。
_ENT_SEP = "_"
# 仅 claude-native 系 harness 注入了全局共享订阅(ADR-027 §4);其余建出来不可用,先限于此。
_ALLOWED_HARNESSES = {"claude-native"}
_DEFAULT_HARNESS = "claude-native"


class _QuotedStr(str):
    """str 子类 → 在 config.yaml 里强制双引号输出(name 值无歧义、分隔符显式落引号内)。"""


def _represent_quoted(dumper: yaml.Dumper, data: _QuotedStr):
    return dumper.represent_scalar("tag:yaml.org,2002:str", str(data), style='"')


yaml.SafeDumper.add_representer(_QuotedStr, _represent_quoted)


def _split_enterprise(name: str) -> tuple[str | None, str]:
    """解 omnigent agent name → (enterprise_alias|None, 剩余部分)。无前缀 = 内置(全局)。
    注:企业 agent 的「剩余部分」是 ASCII slug(非人类展示名 —— 展示名在 description);
    内置 agent 无前缀,剩余部分即其 omnigent name(也就是内置的展示名)。归属判定只看前缀。"""
    if _ENT_SEP in name:
        alias, _, rest = name.partition(_ENT_SEP)
        return alias, rest
    return None, name


def _visible_to(name: str, alias: str) -> bool:
    """该 agent(按 name 前缀)对 alias 企业是否可见:内置(无前缀)或前缀==alias。"""
    owner, _ = _split_enterprise(name)
    return owner is None or owner == alias


def _ascii_slug(display: str) -> str:
    """把(任意 Unicode)展示名压成 ASCII slug,供 omnigent name 后缀(name 仅许 [a-zA-Z0-9_-])。
    非 ASCII 字符无损映射不到则丢弃 → 可能为空(纯中文名);为空时由调用方兜底。"""
    folded = unicodedata.normalize("NFKD", display).encode("ascii", "ignore").decode("ascii")
    # name 后缀绝不含 "_"(那是企业前缀分隔符,会被 partition 误切)→ 只留字母数字与连字符。
    slug = re.sub(r"[^a-zA-Z0-9-]+", "-", folded).strip("-")
    return slug[:32]


def _enterprise_name(alias: str, display: str) -> str:
    """据【已认证会话】alias 构造 omnigent agent name = "<alias>_<ascii-slug>-<rand>"。
    omnigent name 只承载【企业归属】+ 人类可读 ASCII 标识(展示名落 description);随机尾防撞。
    结果保证匹配 ^[a-zA-Z0-9_-]+$(alias 本身 ASCII 字母数字+连字符,slug 已净化)。"""
    base = _ascii_slug(display)
    token = secrets.token_hex(3)   # 6 位 hex(ASCII)→ 重名/纯非 ASCII 名也得唯一 name
    suffix = f"{base}-{token}" if base else f"agent-{token}"
    return f"{alias}{_ENT_SEP}{suffix}"


# 人类展示名(任意 Unicode)进不了 omnigent name(只许 [a-zA-Z0-9_-])→ 落 description。
# description 编码:首行 = 展示名,空行后(可选)= 用户描述。读时拆回。
def _encode_description(display: str, user_desc: str | None) -> str:
    return f"{display}\n\n{user_desc}" if user_desc else display


def _decode_description(raw: str) -> tuple[str, str]:
    """description → (展示名, 用户描述)。首行 = 展示名;空行后余下 = 用户描述。
    内置模板的 description 无此编码(无展示名行约定)→ 调用方对内置不取展示名。"""
    display, _, rest = raw.partition("\n\n")
    return display.strip(), rest.strip()


def _build_bundle_bytes(*, name: str, instructions: str | None, harness: str,
                        model: str | None, description: str | None) -> bytes:
    """搭只含【安全字段】的 .tar.gz(内含 config.yaml)。绝不写 mcp/env/auth/capability —
    fork 的安全白名单只允许 name/description/instructions/executor(type+harness)/llm.model。"""
    spec: dict = {
        "spec_version": 1,
        # name 强制双引号 → 值无歧义(分隔符 "_" 也显式落在引号内,绝不被 YAML 解析吃掉)。
        "name": _QuotedStr(name),
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
            owner, _ = _split_enterprise(name)   # 归属判定仍纯靠 name 前缀(隔离逻辑不变)
            raw_desc = a.get("description", "") or ""
            if owner is None:
                # 内置模板:无展示名编码,直接用 omnigent name 当展示名 + 原样 description。
                display, user_desc = name, raw_desc
            else:
                # 本企业 agent:展示名(可含中文)在 description 首行,空行后为用户描述。
                display, user_desc = _decode_description(raw_desc)
            out.append({"id": a.get("id"), "name": display, "harness": a.get("harness"),
                        "description": user_desc,
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
        if _ENT_SEP in display:   # 客户端绝不能在展示名里带分隔符 "_"(防越界伪造企业前缀;纵深防御)
            return JSONResponse(status_code=400, content={"reason": "invalid name"})
        harness = ((body or {}).get("harness") or _DEFAULT_HARNESS).strip()
        if harness not in _ALLOWED_HARNESSES:   # 只允许已注入全局凭据的可用 harness
            return JSONResponse(status_code=400,
                                content={"reason": f"unsupported harness: {harness}"})
        instructions = (body or {}).get("instructions") or None
        model = ((body or {}).get("model") or "").strip() or None
        user_desc = (body or {}).get("description") or None
        # 企业前缀来自【已认证会话】alias,绝非客户端输入 → 归属不可伪造。
        # name 只承载企业归属 + ASCII slug;人类展示名(可含中文)落 description 首行。
        ent_name = _enterprise_name(alias, display)
        bundle = _build_bundle_bytes(name=ent_name, instructions=instructions, harness=harness,
                                     model=model,
                                     description=_encode_description(display, user_desc))
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
        # 回前端:展示名(人类名,非 omnigent 的内部 name)+ 用户描述;前端永不见企业前缀/内部 name。
        return JSONResponse(status_code=200, content={
            "id": agent_id, "name": display, "harness": obj.get("harness", harness),
            "description": user_desc or "",
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
