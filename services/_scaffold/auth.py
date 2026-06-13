# services/_scaffold/auth.py
from __future__ import annotations
import json, os

from fastapi import Request, HTTPException
from libs.identity.context import parse_context, Context
from libs.identity.tokens import verify_and_decode


def context_from_request(request: Request) -> Context:
    """所有服务共享:Bearer JWT → Keycloak JWKS 验签 → Context。
    测试 seam(x-test-claims)**默认关闭**(default-deny);仅 LITEAI_ALLOW_TEST_CLAIMS=1 开启。
    LITEAI_TOKEN_ISSUER/AUDIENCE 给定时强制校验(防 token-confusion)。"""
    raw = request.headers.get("x-test-claims")
    if raw and os.getenv("LITEAI_ALLOW_TEST_CLAIMS", "0") == "1":
        try:
            c = json.loads(raw)
        except ValueError:
            raise HTTPException(status_code=401, detail="invalid test claims")
        return parse_context(sub=c["sub"], groups=c.get("groups", []))
    authz = request.headers.get("authorization", "")
    if not authz.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="unauthenticated")
    try:
        claims = verify_and_decode(authz[7:], jwks_url=os.environ["LITEAI_JWKS_URL"],
                                   audience=os.getenv("LITEAI_TOKEN_AUDIENCE"),
                                   issuer=os.getenv("LITEAI_TOKEN_ISSUER"))
    except Exception:
        raise HTTPException(status_code=401, detail="invalid token")
    return parse_context(sub=claims["sub"], groups=claims.get("groups", []))
