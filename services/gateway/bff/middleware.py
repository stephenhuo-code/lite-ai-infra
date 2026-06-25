# services/gateway/bff/middleware.py —— BFF 会话中间件 + bearer 注入 + 过期刷新 + /auth/me(Task 5)
# 取代原"透传客户端 bearer":bearer 只从会话 cookie 解出注入下游(C-1 命门,配 proxy 删 authorization 转发)。
from __future__ import annotations

import asyncio
import os
import time

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from libs.identity.context import parse_context
from libs.identity.tokens import verify_and_decode
from services._scaffold.auth import _as_list
from services.gateway.bff import oidc
from services.gateway.bff.orgs import OrgInviter
from services.gateway.bff.routes import make_auth_router
from services.gateway.bff.session import (
    SESSION_COOKIE,
    SessionCodec,
    SessionData,
    clear_session_cookies,
    set_session_only,
)


def _secure() -> bool:
    return os.getenv("BFF_COOKIE_SECURE", "0") == "1"


def _is_protected(path: str) -> bool:
    # 受保护:业务反代 /v1/* 与会话自省 /auth/me;公开:/auth/login·callback·logout、/healthz、/docs 等
    return path.startswith("/v1/") or path == "/auth/me"


# CSRF(C-3 双提交):变更方法严格校验 X-CSRF-Token == 会话内 csrf。
_MUTATING = {"POST", "PUT", "DELETE", "PATCH"}
# 豁免清单**定死**:/auth/login·/auth/callback(均 GET,本就豁免;列此防误改成非 GET)。
# **/auth/logout(POST)不豁免**——需 CSRF,防 CSRF 强制登出。所有 GET 豁免(副作用端点严格非 GET)。
_CSRF_EXEMPT = {"/auth/login", "/auth/callback"}


def _csrf_ok(request: Request, sd) -> bool:
    # 校验 header == 会话内 csrf(非仅 == 明文 cookie,防 cookie 注入篡改双提交一致性)
    return sd is not None and bool(sd.csrf) and request.headers.get("x-csrf-token", "") == sd.csrf


class RefreshCoordinator:
    """I-1 single-flight:并发同一旧 refresh token 的刷新**共享一次结果**(非仅串行)。
    进锁后 double-check:已有并发请求刚刷出结果 → 复用、不重复刷 —— 否则(prod 若开
    Revoke Refresh Token / rotation)后到请求拿失效旧 refresh 去刷会随机登出(I-2 死结)。
    Task 1 实测 dev rotation 关(直刷亦安全),此处仍单飞以防 prod 开 rotation(probe.md §2)。
    _results/_locks 按旧 refresh token 键,带上限防无界增长(v1 单副本;v2 换中心会话存储是 seam)。"""

    def __init__(self, refresh_fn, cap: int = 512):
        self._fn = refresh_fn
        self._cap = cap
        self._locks: dict[str, asyncio.Lock] = {}
        self._results: dict[str, dict] = {}

    async def refresh(self, old_rt: str) -> dict:
        lock = self._locks.get(old_rt)
        if lock is None:
            lock = self._locks[old_rt] = asyncio.Lock()
        async with lock:
            if old_rt in self._results:               # double-check:并发已刷 → 复用
                return self._results[old_rt]
            try:
                tok = await run_in_threadpool(self._fn, old_rt)   # refresh_fn 同步 httpx,不阻塞事件循环
            except Exception:
                # I-4 刷新失败:不缓存结果,且**清掉本 key 的锁**防泄漏(否则失败的 logged-out
                # 用户的旧 refresh 会在 _locks 永久留存 → 长期单进程慢泄漏)。下次同 key 重建锁重试。
                self._locks.pop(old_rt, None)
                raise
            self._results[old_rt] = tok
            if len(self._results) > self._cap:        # 防无界增长(FIFO 淘汰最早;同 key 同时从两表移除)
                oldest = next(iter(self._results))
                self._locks.pop(oldest, None)
                self._results.pop(oldest, None)
            return tok


def _claim_org_roles(c: dict) -> tuple[list[str], list[str]]:
    """从 token claims 取 organization(alias 数组,multivalued=false 单字符串归一)+ realm 角色。
    organization 归一与 scaffold/auth 共用 _as_list(含 None 守卫:RESULTS F3 多-org bug 可能发 null)。"""
    organization = _as_list(c.get("organization"))
    realm_roles = (c.get("realm_access") or {}).get("roles", [])
    return organization, realm_roles


def install_bff(app: FastAPI, *, exchange_code=None, refresh_fn=None, claims_fn=None, inviter=None) -> None:
    """把 BFF 装到 gateway app:auth 路由(login/callback/logout)+ 会话中间件 + /auth/me + 企业邀请。
    seam:
      exchange_code(code, verifier)->token  —— 默认真 KC code 交换(lite-ai-web)
      refresh_fn(refresh_token)->token      —— 默认真 KC refresh
      claims_fn(access_token)->claims dict  —— 默认 JWKS 验签解码(/auth/me 解会话内 access,M-3)
      inviter.invite(org_alias, email)      —— 默认真 KC org 邀请(enterprise-admin 调)
    """
    cfg = oidc.OidcConfig()
    codec = SessionCodec(os.environ["BFF_SESSION_KEY"].encode())
    coordinator = RefreshCoordinator(refresh_fn or (lambda rt: oidc.refresh_tokens(cfg, rt)))
    org_inviter = inviter or OrgInviter()

    def _default_claims(token: str) -> dict:
        return verify_and_decode(token, jwks_url=os.environ["LITEAI_JWKS_URL"],
                                 audience=os.getenv("LITEAI_TOKEN_AUDIENCE"),
                                 issuer=os.getenv("LITEAI_TOKEN_ISSUER"))

    claims = claims_fn or _default_claims

    app.include_router(make_auth_router(exchange_code=exchange_code))

    @app.get("/auth/me")
    def auth_me(request: Request):
        # 解**会话内 access token** 的 claims(M-3:不存 id_token、不多跳 identity)
        sd: SessionData | None = getattr(request.state, "session", None)
        bearer = getattr(request.state, "bearer", None)
        if sd is None or not bearer:
            return JSONResponse(status_code=401, content={"reason": "unauthenticated"})
        try:
            c = claims(bearer)
        except Exception:
            return JSONResponse(status_code=401, content={"reason": "invalid token"})
        organization, realm_roles = _claim_org_roles(c)
        ctx = parse_context(sub=c["sub"], organization=organization, realm_roles=realm_roles)
        # 真实展示信息(来自 Keycloak token claims):用户名优先 preferred_username,回退 name;邮箱可空。
        # user(sub,§1.4 不透明)仍返回供前端内部使用;界面展示用 username/email。
        # enterprises:企业归属(org alias);企业显示名不在 token(F1),由 /v1/me/orgs 解析。
        return {"user": ctx.user, "is_platform_admin": ctx.is_platform_admin, "csrf": sd.csrf,
                "username": c.get("preferred_username") or c.get("name") or ctx.user,
                "email": c.get("email"),
                "enterprises": [m.enterprise_id for m in ctx.memberships]}

    @app.post("/auth/orgs/invite")
    async def invite_member(request: Request):
        # 企业邀请(enterprise-admin):会话取 caller 的 org(alias)+ 角色 → 仅 ent-admin 放行 →
        # KC org 邀请。CSRF 由会话中间件强制(变更方法非豁免)。
        sd: SessionData | None = getattr(request.state, "session", None)
        bearer = getattr(request.state, "bearer", None)
        if sd is None or not bearer:
            return JSONResponse(status_code=401, content={"reason": "unauthenticated"})
        try:
            c = claims(bearer)
        except Exception:
            return JSONResponse(status_code=401, content={"reason": "invalid token"})
        try:
            body = await request.json()
        except Exception:
            body = {}
        email = (body or {}).get("email", "").strip()
        if not email:
            return JSONResponse(status_code=400, content={"reason": "email required"})
        organization, realm_roles = _claim_org_roles(c)
        ctx = parse_context(sub=c["sub"], organization=organization, realm_roles=realm_roles)
        aliases: list[str] = []
        for m in ctx.memberships:
            if m.enterprise_id not in aliases:
                aliases.append(m.enterprise_id)
        if len(aliases) != 1:   # v1 单企业:0/多企业显式拒(不静默挑第一个)
            return JSONResponse(status_code=400, content={"reason": "ambiguous enterprise membership"})
        alias = aliases[0]
        if ctx.role_in(alias) != "enterprise-admin":   # 仅企业管理员可邀请
            return JSONResponse(status_code=403, content={"reason": "enterprise-admin only"})
        try:
            org_inviter.invite(alias, email)
        except Exception:
            return JSONResponse(status_code=502, content={"reason": "invite failed"})
        return {"ok": True}

    @app.middleware("http")
    async def _session(request: Request, call_next):
        # ===== call_next 前:解会话 → (过期则刷新) → 设 request.state.bearer/session =====
        path = request.url.path
        raw = request.cookies.get(SESSION_COOKIE)
        sd = codec.decode(raw) if raw else None
        new_session: SessionData | None = None
        clear = False
        if sd is not None and sd.is_expired(int(time.time())):
            if sd.refresh_token:
                try:
                    tok = await coordinator.refresh(sd.refresh_token)
                    sd = SessionData(access_token=tok["access_token"],
                                     refresh_token=tok.get("refresh_token", sd.refresh_token),
                                     expires_at=int(time.time()) + int(tok["expires_in"]),
                                     csrf=sd.csrf)
                    new_session = sd                  # C-2:待下发到当前响应
                except Exception:
                    sd, clear = None, True            # I-4:刷新失败 → 清 cookie + 401(不抛 500)
            else:
                sd, clear = None, True                # 过期且无 refresh → 等同未登录
        if sd is not None:
            request.state.bearer = sd.access_token    # C-1:bearer 唯一来源 = 会话
            request.state.session = sd
        # 受保护路由无有效会话 → 401(在 call_next 前,绝不进反代)
        if _is_protected(path) and sd is None:
            resp = JSONResponse(status_code=401, content={"reason": "unauthenticated"})
            if clear:
                clear_session_cookies(resp, secure=_secure())
            return resp
        # CSRF 双提交(C-3):变更方法(非豁免)需 X-CSRF-Token == 会话内 csrf,否则 403
        if request.method in _MUTATING and path not in _CSRF_EXEMPT and not _csrf_ok(request, sd):
            return JSONResponse(status_code=403, content={"reason": "csrf"})
        # ===== call_next 后:刷新出的新会话随当前响应 Set-Cookie 下发(C-2)=====
        response = await call_next(request)
        if new_session is not None:
            set_session_only(response, codec, new_session, secure=_secure())
        return response
