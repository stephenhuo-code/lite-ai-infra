# services/gateway/deps.py
import json, os
from fastapi import Request, HTTPException
from libs.identity.context import parse_context, Context
from libs.identity.tokens import verify_and_decode


def context_from_request(request: Request) -> Context:
    # 测试 seam:**默认关闭**(default-deny,宪法 §5.2)。仅显式设
    # LITEAI_ALLOW_TEST_CLAIMS=1(单测/本地调试)才接受预解码 claims。
    raw = request.headers.get("x-test-claims")
    if raw and os.getenv("LITEAI_ALLOW_TEST_CLAIMS", "0") == "1":
        try:
            c = json.loads(raw)
        except ValueError:
            raise HTTPException(status_code=401, detail="invalid test claims")
        return parse_context(sub=c["sub"], groups=c.get("groups", []))
    # 生产:Bearer JWT → Keycloak JWKS 验签 → 解析。无/非法 token → 401。
    # LITEAI_TOKEN_ISSUER / LITEAI_TOKEN_AUDIENCE 给定时强制校验(防 token-confusion)。
    authz = request.headers.get("authorization", "")
    if not authz.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="unauthenticated")
    try:
        claims = verify_and_decode(
            authz[7:],
            jwks_url=os.environ["LITEAI_JWKS_URL"],
            audience=os.getenv("LITEAI_TOKEN_AUDIENCE"),
            issuer=os.getenv("LITEAI_TOKEN_ISSUER"),
        )
    except Exception:
        raise HTTPException(status_code=401, detail="invalid token")
    return parse_context(sub=claims["sub"], groups=claims.get("groups", []))
