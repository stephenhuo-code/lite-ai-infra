# libs/identity/tokens.py
from __future__ import annotations
from functools import lru_cache

import jwt
from jwt import PyJWKClient


@lru_cache(maxsize=8)
def _jwks_client(jwks_url: str) -> PyJWKClient:
    """每个 jwks_url 复用同一 PyJWKClient(内部缓存 JWKS),避免每请求一次 HTTP 拉取。"""
    return PyJWKClient(jwks_url)


def verify_and_decode(token: str, jwks_url: str,
                      audience: str | None = None,
                      issuer: str | None = None) -> dict:
    """用 Keycloak JWKS 验签并解码 access token。验签失败抛 jwt 异常。

    audience/issuer 给定时强制校验(防 token-confusion:同 realm 其他 client
    签发的 token 不得被本服务接受);None 时跳过对应校验(本地/集成测试)。
    """
    key = _jwks_client(jwks_url).get_signing_key_from_jwt(token).key
    return jwt.decode(token, key, algorithms=["RS256"],
                      audience=audience, issuer=issuer,
                      options={"verify_aud": audience is not None,
                               "verify_iss": issuer is not None})
