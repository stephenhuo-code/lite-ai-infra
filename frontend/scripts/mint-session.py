"""browserless 造 BFF 会话 cookie,供 Playwright 注入(复用 Plan 6 SessionCodec,免在浏览器走 OIDC)。

打印 JSON {cookie, session, csrf} 到 stdout。会话自举方式同 scripts/accept_bff.py:
ROPC(gateway 客户端)拿真 Keycloak token → SessionCodec(同 dev BFF_SESSION_KEY)加密成会话 cookie。
env:KC / KC_SECRET / KC_USER / KC_PASS / BFF_SESSION_KEY(默认 = dev_services.sh / Makefile 的 dev 值)。
"""
import json
import os
import sys
import time

import httpx

# 仓库根入 path(从 frontend/scripts 上两级 → repo root),直接 import 真实 BFF 会话编解码
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from services.gateway.bff.session import SESSION_COOKIE, SessionCodec, SessionData  # noqa: E402

KC = os.environ.get("KC", "http://localhost:8080/realms/lite-ai")
KEY = os.environ.get("BFF_SESSION_KEY", "5SetoEInIYji6K_tuQEB8pJ8NCaoC5yi2vNAxtPi7gg=")
CSRF = "csrf-e2e"

tok = (
    httpx.post(
        f"{KC}/protocol/openid-connect/token",
        timeout=15,
        data={
            "client_id": "gateway",
            "client_secret": os.environ.get("KC_SECRET", "dev-secret"),
            "username": os.environ.get("KC_USER", "alice"),
            "password": os.environ.get("KC_PASS", "alice"),
            "grant_type": "password",
        },
    )
    .raise_for_status()
    .json()["access_token"]
)

# SessionData(access_token, refresh_token, expires_at, csrf="")（真实签名,refresh 可为 None）
sd = SessionData(tok, None, int(time.time()) + 300, csrf=CSRF)
print(json.dumps({
    "cookie": SESSION_COOKIE,
    "session": SessionCodec(KEY.encode()).encode(sd),
    "csrf": CSRF,
}))
