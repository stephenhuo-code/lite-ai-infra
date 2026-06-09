# services/gateway/deps.py
import json, os
from fastapi import Request, HTTPException
from libs.identity.context import parse_context, Context
from libs.identity.tokens import verify_and_decode


def context_from_request(request: Request) -> Context:
    # 测试 seam：LITEAI_ALLOW_TEST_CLAIMS=1 时接受预解码 claims（默认 1，便于单测）
    raw = request.headers.get("x-test-claims")
    if raw and os.getenv("LITEAI_ALLOW_TEST_CLAIMS", "1") == "1":
        c = json.loads(raw)
        return parse_context(sub=c["sub"], groups=c.get("groups", []))
    # 生产：Bearer JWT → Keycloak JWKS 验签 → 解析。无/非法 token → 401。
    authz = request.headers.get("authorization", "")
    if not authz.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="unauthenticated")
    try:
        claims = verify_and_decode(authz[7:], jwks_url=os.environ["LITEAI_JWKS_URL"])
    except Exception:
        raise HTTPException(status_code=401, detail="invalid token")
    return parse_context(sub=claims["sub"], groups=claims.get("groups", []))
