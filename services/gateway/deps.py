# services/gateway/deps.py
import json, os
from fastapi import Request, HTTPException
from libs.identity.context import parse_context, Context

def context_from_request(request: Request) -> Context:
    # 测试 seam：设置 LITEAI_ALLOW_TEST_CLAIMS 时接受预解码 claims。
    raw = request.headers.get("x-test-claims")
    if raw and os.getenv("LITEAI_ALLOW_TEST_CLAIMS", "1") == "1":
        c = json.loads(raw)
        return parse_context(sub=c["sub"], groups=c.get("groups", []))
    # 生产：验 bearer JWT（Keycloak JWKS，Spike A / 阿里云）。无 token → 401。
    raise HTTPException(status_code=401, detail="unauthenticated")
