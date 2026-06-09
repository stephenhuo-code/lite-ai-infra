# libs/identity/tokens.py
from __future__ import annotations
import jwt
from jwt import PyJWKClient


def verify_and_decode(token: str, jwks_url: str, audience: str | None = None) -> dict:
    """用 Keycloak JWKS 验签并解码 access token。验签失败抛 jwt 异常。"""
    key = PyJWKClient(jwks_url).get_signing_key_from_jwt(token).key
    return jwt.decode(token, key, algorithms=["RS256"],
                      audience=audience, options={"verify_aud": audience is not None})
