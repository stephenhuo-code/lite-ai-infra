# services/_scaffold/auth.py
from __future__ import annotations
import json, os

from fastapi import Request, HTTPException
from libs.identity.context import parse_context, Context
from libs.identity.tokens import verify_and_decode


def _as_list(v) -> list[str]:
    """KC organization claim:multivalued=true 为 list、=false 为单字符串 → 统一成 list。"""
    if v is None:
        return []
    return list(v) if isinstance(v, list) else [v]


def enterprise_of(ctx: Context) -> str:
    """v1 单企业:从 token 推导调用者企业;属 0/多个企业显式拒(宪法 §3.7,不静默挑第一个)。"""
    ents = []
    for m in ctx.memberships:
        if m.enterprise_id not in ents:
            ents.append(m.enterprise_id)
    if not ents:
        raise HTTPException(status_code=403, detail="no enterprise membership")
    if len(ents) > 1:
        raise HTTPException(status_code=400, detail="ambiguous enterprise membership; v1 single-enterprise only")
    return ents[0]


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
        # 测试 seam:扁平 organization(alias 数组)+ realm_roles
        return parse_context(sub=c["sub"], organization=_as_list(c.get("organization")),
                             realm_roles=_as_list(c.get("realm_roles")))
    authz = request.headers.get("authorization", "")
    if not authz.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="unauthenticated")
    try:
        claims = verify_and_decode(authz[7:], jwks_url=os.environ["LITEAI_JWKS_URL"],
                                   audience=os.getenv("LITEAI_TOKEN_AUDIENCE"),
                                   issuer=os.getenv("LITEAI_TOKEN_ISSUER"))
    except Exception:
        raise HTTPException(status_code=401, detail="invalid token")
    # KC token:organization claim 在顶层(org alias 数组),角色在 realm_access.roles
    return parse_context(sub=claims["sub"], organization=_as_list(claims.get("organization")),
                         realm_roles=(claims.get("realm_access") or {}).get("roles", []))
