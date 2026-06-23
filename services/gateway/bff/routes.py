# services/gateway/bff/routes.py —— BFF auth 路由(Task 4):/auth/login · /auth/callback · /auth/logout
# login:生成 state+verifier 存临时加密 cookie + 302 到 Keycloak authorize(PKCE S256)。
# callback:校验 state(I-3)→ exchange_code(可注入 seam)→ 生成 csrf → 建加密会话 cookie +
#          明文 csrf_token 副本(双提交唯一写入点)→ 清临时 cookie → 302 回 /。
# logout:清会话 + csrf cookie(Max-Age=0)。CSRF 强制在 Task 6 中间件(logout 需 CSRF)。
from __future__ import annotations

import json
import os
import time

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse

from services.gateway.bff import oidc
from services.gateway.bff.session import (
    ID_TOKEN_COOKIE,
    STATE_COOKIE,
    SessionCodec,
    SessionData,
    clear_session_cookies,
    set_id_token_cookie,
    set_session_cookies,
)


def _secure() -> bool:
    return os.getenv("BFF_COOKIE_SECURE", "0") == "1"


def make_auth_router(exchange_code=None) -> APIRouter:
    """auth 路由工厂。exchange_code(code, verifier)->token dict:测试注入 fake;
    默认打真 Keycloak token 端点(lite-ai-web + secret)。env 在路由构建时读取(main/测试均先设好)。"""
    cfg = oidc.OidcConfig()
    key = os.environ["BFF_SESSION_KEY"].encode()
    codec = SessionCodec(key)
    fernet = Fernet(key)                       # 临时 oidc_state cookie 用同一 key 加密
    _exchange = exchange_code or (lambda code, verifier: oidc.exchange_code(cfg, code, verifier))

    router = APIRouter()

    @router.get("/auth/login")
    def login():
        state = oidc.gen_state()
        verifier = oidc.gen_verifier()
        challenge = oidc.challenge_from(verifier)
        temp = fernet.encrypt(json.dumps({"state": state, "verifier": verifier}).encode()).decode()
        resp = RedirectResponse(oidc.authorize_url(cfg, state, challenge), status_code=302)
        # 临时 state/verifier:HttpOnly、短 TTL(600s),callback 后即清
        resp.set_cookie(STATE_COOKIE, temp, max_age=600, httponly=True,
                        samesite="lax", secure=_secure(), path="/")
        return resp

    @router.get("/auth/callback")
    def callback(request: Request, code: str = "", state: str = ""):
        raw = request.cookies.get(STATE_COOKIE)
        if not raw:
            return JSONResponse(status_code=400, content={"reason": "missing oidc state"})
        try:
            saved = json.loads(fernet.decrypt(raw.encode()))
        except (InvalidToken, ValueError):
            return JSONResponse(status_code=400, content={"reason": "bad oidc state"})
        if not state or state != saved.get("state"):     # I-3:state 不匹配硬拒
            return JSONResponse(status_code=400, content={"reason": "state mismatch"})
        try:
            tok = _exchange(code, saved["verifier"])      # code + PKCE verifier → token
        except Exception:
            return JSONResponse(status_code=400, content={"reason": "code exchange failed"})
        csrf = oidc.gen_state()                           # 双提交 CSRF:登录回调一次生成(I-3)
        sd = SessionData(access_token=tok["access_token"], refresh_token=tok.get("refresh_token"),
                         expires_at=int(time.time()) + int(tok["expires_in"]), csrf=csrf)
        resp = RedirectResponse("/", status_code=302)
        set_session_cookies(resp, codec, sd, secure=_secure())   # 会话 + 明文 csrf 副本(同值)
        set_id_token_cookie(resp, tok.get("id_token", ""), secure=_secure())  # id_token 单独 cookie(登出 id_token_hint;不撑大会话)
        resp.set_cookie(STATE_COOKIE, "", max_age=0, httponly=True, samesite="lax", path="/")  # 清临时
        return resp

    @router.post("/auth/logout")
    def logout(request: Request):
        # RP-initiated logout:从独立 id_token cookie 取 hint(best-effort)→ 拼 KC end_session(结束 SSO)→ 清本地 cookie。
        id_token = request.cookies.get(ID_TOKEN_COOKIE, "")
        origin = cfg.redirect_uri.rsplit("/auth/callback", 1)[0]   # http://localhost:8090
        end_session = oidc.end_session_url(
            cfg, id_token_hint=id_token, post_logout_redirect_uri=f"{origin}/auth/login")
        resp = JSONResponse({"ok": True, "end_session": end_session})
        clear_session_cookies(resp, secure=_secure())     # session + csrf Max-Age=0
        return resp

    return router


def build_auth_router_app(exchange_code=None) -> FastAPI:
    """测试用最小 app:只挂 auth 路由(无反代/会话中间件)。"""
    app = FastAPI()
    app.include_router(make_auth_router(exchange_code=exchange_code))
    return app
