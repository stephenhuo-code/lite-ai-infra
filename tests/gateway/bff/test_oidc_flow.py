# tests/gateway/bff/test_oidc_flow.py —— Task 4:OIDC code+PKCE login/callback/logout(TDD)
import urllib.parse

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from services.gateway.bff.routes import build_auth_router_app


def _app(monkeypatch):
    monkeypatch.setenv("BFF_SESSION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("OIDC_CLIENT_ID", "lite-ai-web")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "s")
    monkeypatch.setenv("OIDC_ISSUER", "http://kc/realms/x")
    monkeypatch.setenv("BFF_REDIRECT_URI", "http://gw/auth/callback")

    # token 端点交换 seam:返回假 token(I-3:真交换用真 KC,测试注入)
    def fake_exchange(code, verifier):
        return {"access_token": "at", "refresh_token": "rt", "expires_in": 300, "id_token": "idtok"}

    return build_auth_router_app(exchange_code=fake_exchange)


def test_login_redirects_to_authorize_with_pkce(monkeypatch):
    r = TestClient(_app(monkeypatch)).get("/auth/login", follow_redirects=False)
    assert r.status_code == 302
    loc = r.headers["location"]
    assert "response_type=code" in loc and "code_challenge=" in loc and "state=" in loc
    assert "code_challenge_method=S256" in loc
    assert "oidc_state" in r.cookies      # 临时 state/verifier cookie 已下发


def test_callback_bad_state_400(monkeypatch):
    c = TestClient(_app(monkeypatch))
    # 无 oidc_state cookie(或 state 不匹配)→ 400(I-3:state 校验硬门)
    assert c.get("/auth/callback?code=x&state=mismatch", follow_redirects=False).status_code == 400


def test_callback_happy_sets_session_and_csrf(monkeypatch):
    c = TestClient(_app(monkeypatch))
    # 先 login 拿到 oidc_state cookie + 真实 state(TestClient 自带 cookie jar 复用)
    r = c.get("/auth/login", follow_redirects=False)
    state = urllib.parse.parse_qs(urllib.parse.urlparse(r.headers["location"]).query)["state"][0]
    # callback:state 匹配 → 换 token(fake)→ 下发会话 + csrf cookie → 302 回 /
    cb = c.get(f"/auth/callback?code=thecode&state={state}", follow_redirects=False)
    assert cb.status_code == 302 and cb.headers["location"] == "/"
    setc = cb.headers.get_list("set-cookie")
    joined = " ".join(setc)
    assert "session=" in joined and "httponly" in joined.lower()
    assert "csrf_token=" in joined            # 非 HttpOnly 明文 csrf 副本(双提交)
    # 会话 cookie 可解出 access token,csrf 字段非空且与明文 cookie 同值
    sess = c.cookies.get("session")
    csrf_cookie = c.cookies.get("csrf_token")
    assert sess and csrf_cookie
    from services.gateway.bff.session import SessionCodec
    import os
    sd = SessionCodec(os.environ["BFF_SESSION_KEY"].encode()).decode(sess)
    assert sd.access_token == "at" and sd.refresh_token == "rt"
    assert sd.csrf == csrf_cookie and sd.csrf != ""
    assert sd.expires_at > 0
    assert c.cookies.get("id_token") == "idtok"   # id_token 落独立 cookie(不进会话 blob,避免 >4KB)


def test_logout_clears_cookie_and_returns_end_session(monkeypatch):
    # 无会话 cookie 直接登出:仍清 cookie + 返回 end_session(降级:无 id_token_hint,但有 post_logout_redirect_uri)
    r = TestClient(_app(monkeypatch)).post("/auth/logout", follow_redirects=False)
    sc = r.headers.get("set-cookie", "")
    assert "session=" in sc and "Max-Age=0" in sc
    body = r.json()
    assert body["ok"] is True
    es = body["end_session"]
    assert es.startswith("http://kc/realms/x/protocol/openid-connect/logout?")
    assert "post_logout_redirect_uri=" in es and "%2Fauth%2Flogin" in es
    assert "client_id=lite-ai-web" in es


def test_logout_includes_id_token_hint_when_session_present(monkeypatch):
    # 登录→回调建会话(含 id_token)→ 登出:end_session 带 id_token_hint=idtok(无缝,跳过 KC 确认页)
    c = TestClient(_app(monkeypatch))
    r = c.get("/auth/login", follow_redirects=False)
    state = urllib.parse.parse_qs(urllib.parse.urlparse(r.headers["location"]).query)["state"][0]
    c.get(f"/auth/callback?code=thecode&state={state}", follow_redirects=False)
    out = c.post("/auth/logout", follow_redirects=False)
    assert "id_token_hint=idtok" in out.json()["end_session"]


def test_end_session_url_unit(monkeypatch):
    # oidc.end_session_url:有 hint 带 hint;无 hint 省略该参(降级)
    from services.gateway.bff import oidc
    _app(monkeypatch)                      # 设好 env 供 OidcConfig 读取
    cfg = oidc.OidcConfig()
    with_hint = oidc.end_session_url(cfg, id_token_hint="ID", post_logout_redirect_uri="http://gw/auth/login")
    assert "id_token_hint=ID" in with_hint and "post_logout_redirect_uri=" in with_hint
    assert "client_id=lite-ai-web" in with_hint
    no_hint = oidc.end_session_url(cfg, id_token_hint="", post_logout_redirect_uri="http://gw/auth/login")
    assert "id_token_hint" not in no_hint
