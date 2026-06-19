# services/gateway/bff/oidc.py —— OIDC Authorization Code + PKCE 原语(Task 4)
# authorize URL 构造 / PKCE S256 / token 交换(code→token、refresh→token)。
# 真交换打 Keycloak token 端点用 lite-ai-web + secret(Task 1 实测路径);测试经 routes 的 exchange_code seam 注入。
from __future__ import annotations

import base64
import hashlib
import os
import secrets
import urllib.parse

import httpx


def gen_verifier() -> str:
    """PKCE code_verifier:43+ 字符 URL-safe(Task 1 实测 KC 接受 S256)。"""
    return base64.urlsafe_b64encode(secrets.token_bytes(40)).rstrip(b"=").decode()


def challenge_from(verifier: str) -> str:
    """PKCE S256 challenge = BASE64URL(SHA256(verifier))。"""
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def gen_state() -> str:
    """CSRF/state:回调时与会话内存比对(I-3 state 校验硬门)。"""
    return secrets.token_urlsafe(24)


class OidcConfig:
    """从 env 读 OIDC 配置(BFF_REDIRECT_URI / OIDC_ISSUER / OIDC_CLIENT_ID / OIDC_CLIENT_SECRET)。"""

    def __init__(self) -> None:
        self.issuer = os.environ["OIDC_ISSUER"]
        self.client_id = os.environ["OIDC_CLIENT_ID"]
        self.client_secret = os.environ["OIDC_CLIENT_SECRET"]
        self.redirect_uri = os.environ["BFF_REDIRECT_URI"]

    @property
    def authorize_endpoint(self) -> str:
        return f"{self.issuer}/protocol/openid-connect/auth"

    @property
    def token_endpoint(self) -> str:
        return f"{self.issuer}/protocol/openid-connect/token"


def authorize_url(cfg: OidcConfig, state: str, code_challenge: str) -> str:
    q = urllib.parse.urlencode({
        "client_id": cfg.client_id,
        "response_type": "code",
        "scope": "openid",
        "redirect_uri": cfg.redirect_uri,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    })
    return f"{cfg.authorize_endpoint}?{q}"


def exchange_code(cfg: OidcConfig, code: str, verifier: str) -> dict:
    """authorization_code + PKCE verifier → token(lite-ai-web + secret)。失败抛 httpx 异常。"""
    r = httpx.post(cfg.token_endpoint, data={
        "grant_type": "authorization_code", "client_id": cfg.client_id,
        "client_secret": cfg.client_secret, "code": code,
        "redirect_uri": cfg.redirect_uri, "code_verifier": verifier,
    }, timeout=30)
    r.raise_for_status()
    return r.json()


def refresh_tokens(cfg: OidcConfig, refresh_token: str) -> dict:
    """refresh_token → 新 token(Task 5 access 过期时)。失败抛 httpx 异常(I-4 调用方降级清 cookie)。"""
    r = httpx.post(cfg.token_endpoint, data={
        "grant_type": "refresh_token", "client_id": cfg.client_id,
        "client_secret": cfg.client_secret, "refresh_token": refresh_token,
    }, timeout=30)
    r.raise_for_status()
    return r.json()
