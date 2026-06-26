# services/gateway/bff/wstoken.py
# 每会话工作区令牌:不透明随机串 → (sub, 企业 alias, 角色, 会话)。带 TTL + 按会话撤销。
# v1 进程内存映射(单 BFF 实例够;多实例 = 换共享存储,此处是唯一改点)。令牌是 agent→MCP 工具的
# 唯一身份凭证(design「数据集受控链路」,Task0 实证:令牌随 URL 抵达我们的 MCP server),
# 故必须不透明 + 短时 + 可撤销。
from __future__ import annotations

import secrets
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class TokenClaims:
    sub: str
    enterprise: str
    role: str
    session: str


@dataclass(frozen=True)
class ResolvedToken:
    sub: str
    enterprise: str
    role: str
    session: str


class WorkspaceTokenStore:
    def __init__(self, ttl_seconds: int = 3600, now=time.time):
        self._ttl = ttl_seconds
        self._now = now
        self._m: dict[str, tuple[TokenClaims, float]] = {}

    def mint(self, claims: TokenClaims) -> str:
        tok = secrets.token_urlsafe(32)
        self._m[tok] = (claims, self._now() + self._ttl)
        return tok

    def resolve(self, token: str) -> ResolvedToken | None:
        rec = self._m.get(token)
        if rec is None:
            return None
        claims, exp = rec
        if self._now() >= exp:
            self._m.pop(token, None)
            return None
        return ResolvedToken(claims.sub, claims.enterprise, claims.role, claims.session)

    def revoke_session(self, session: str) -> int:
        gone = [t for t, (c, _) in self._m.items() if c.session == session]
        for t in gone:
            self._m.pop(t, None)
        return len(gone)
