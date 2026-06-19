# tests/integration/test_bff_oidc.py —— Task 8:BFF OIDC 全链路集成(真 Keycloak)
# 标 integration(默认不跑;`make up` 后 `uv run pytest -q -m integration`)。
# 出口⑤ BFF 侧自动验收证据;完整真浏览器 code 流另由人工 runbook(plan 文末验收 1)复验。
import re
import socket
import time
import urllib.parse

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration

KEY = Fernet.generate_key()
KC = "http://localhost:8080/realms/lite-ai"
JWKS = f"{KC}/protocol/openid-connect/certs"
REDIR = "http://localhost:8090/auth/callback"


def _kc_up() -> bool:
    try:
        with socket.create_connection(("localhost", 8080), timeout=1):
            return True
    except OSError:
        return False


class _MemSink:
    def put(self, key, body):
        pass


def _build(monkeypatch, tmp_path):
    """真 data-pipeline 作下游(真 JWKS 验签注入的 bearer)+ 完整 BFF 网关(与 main.py 同序装配)。"""
    monkeypatch.setenv("LITEAI_JWKS_URL", JWKS)
    monkeypatch.setenv("BFF_SESSION_KEY", KEY.decode())
    monkeypatch.setenv("OIDC_CLIENT_ID", "lite-ai-web")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "dev-web-secret")
    monkeypatch.setenv("OIDC_ISSUER", KC)
    monkeypatch.setenv("BFF_REDIRECT_URI", REDIR)
    monkeypatch.delenv("LITEAI_ALLOW_TEST_CLAIMS", raising=False)   # 下游走真 JWKS,非 test-claims seam

    from libs.audit.oss_audit import AuditWriter
    from services._scaffold.app import install_request_id
    from services.data_pipeline_service.app import build_app
    from services.data_pipeline_service.jobs import JobStore
    from services.data_pipeline_service.scheduler import SubprocessJobRunner
    from services.gateway.app import build_gateway
    from services.gateway.bff.middleware import install_bff

    dp = build_app(runner=SubprocessJobRunner(JobStore(str(tmp_path)), spawn=lambda a, **k: None),
                   audit=AuditWriter(_MemSink()))
    transport = httpx.ASGITransport(app=dp)
    app = build_gateway(routes={
        "/v1/data": ("http://dp", lambda: httpx.AsyncClient(transport=transport, base_url="http://dp")),
    }, with_request_id=False)
    install_bff(app)
    install_request_id(app)
    return app


def _ropc_token() -> str:
    r = httpx.post(f"{KC}/protocol/openid-connect/token",
                   data={"client_id": "gateway", "client_secret": "dev-secret",
                         "username": "alice", "password": "alice", "grant_type": "password"})
    r.raise_for_status()
    return r.json()["access_token"]


def test_bff_full_chain_with_real_token(monkeypatch, tmp_path):
    """会话 cookie(真 ROPC token)→ /auth/me 真验签;CSRF;bearer 注入下游真验签 + can() 过滤。"""
    if not _kc_up():
        pytest.skip("Keycloak 未启动(先 `make up`)")
    from services.gateway.bff.session import SESSION_COOKIE, SessionCodec, SessionData

    app = _build(monkeypatch, tmp_path)
    c = TestClient(app)
    sd = SessionData(_ropc_token(), None, int(time.time()) + 300, csrf="csrf-int")
    c.cookies.set(SESSION_COOKIE, SessionCodec(KEY).encode(sd))

    # A) /auth/me:真 JWKS 验签解会话内 access → user + csrf
    me = c.get("/auth/me")
    assert me.status_code == 200 and me.json()["user"] and me.json()["csrf"] == "csrf-int"

    # B) 无会话 → 401
    assert TestClient(app).get("/v1/data/jobs").status_code == 401

    # C) 变更请求缺 CSRF → 403
    body = {"dataset": "cc3m", "group_id": "g-0001", "tar_dir": "/tmp/tars"}
    assert c.post("/v1/data/prepare", json=body).status_code == 403

    # D) 带 CSRF 提交 → 202(下游收到注入 bearer 并**真验签通过** + can() 放行)
    r = c.post("/v1/data/prepare", headers={"X-CSRF-Token": "csrf-int"}, json=body)
    assert r.status_code == 202

    # E) 列作业 → 200 且见刚提交的(can() 过滤后 total≥1)
    jl = c.get("/v1/data/jobs")
    assert jl.status_code == 200 and jl.json()["total"] >= 1
    assert all(j["group_id"] == "g-0001" for j in jl.json()["jobs"])


def test_bff_real_code_pkce_login_through_callback(monkeypatch, tmp_path):
    """真 OIDC code+PKCE 全链路经 BFF:/auth/login → 真 KC 登录 → /auth/callback 真换 token → 会话生效。"""
    if not _kc_up():
        pytest.skip("Keycloak 未启动(先 `make up`)")
    app = _build(monkeypatch, tmp_path)
    c = TestClient(app)

    # 1) BFF /auth/login → 302 到 KC authorize(带 BFF 生成的 state+challenge)+ oidc_state cookie 入 jar
    login = c.get("/auth/login", follow_redirects=False)
    assert login.status_code == 302
    authorize_url = login.headers["location"]
    state = urllib.parse.parse_qs(urllib.parse.urlparse(authorize_url).query)["state"][0]

    # 2) 用真 KC 完成 alice 登录(脚本化表单),拿回 callback 的 code。
    #    注:httpx 会把 localhost cookie 的域名改写成 localhost.local 而**不再回发**(KC 报
    #    "Restart login cookie not found")→ 手动拼 Cookie 头透传 KC 会话 cookie(curl 无此坑)。
    kc = httpx.Client(follow_redirects=False)
    html = kc.get(authorize_url).text
    action = re.search(r'action="([^"]+)"', html).group(1).replace("&amp;", "&")
    cookie_hdr = "; ".join(f"{c.name}={c.value}" for c in kc.cookies.jar)
    resp = kc.post(action, data={"username": "alice", "password": "alice"},
                   headers={"content-type": "application/x-www-form-urlencoded", "cookie": cookie_hdr})
    loc = resp.headers.get("location", "")
    code = urllib.parse.parse_qs(urllib.parse.urlparse(loc).query).get("code", [None])[0]
    assert code, f"KC 未返回 code(loc={loc[:120]})"

    # 3) BFF /auth/callback(oidc_state cookie 在 jar)→ 真 code+verifier 换 token → 会话 cookie + 302 /
    cb = c.get(f"/auth/callback?code={code}&state={state}", follow_redirects=False)
    assert cb.status_code == 302 and cb.headers["location"] == "/"

    # 4) 新会话生效:/auth/me 200(整条真 code+PKCE 链路通)
    me = c.get("/auth/me")
    assert me.status_code == 200 and me.json()["user"]
