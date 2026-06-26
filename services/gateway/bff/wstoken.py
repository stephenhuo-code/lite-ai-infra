# services/gateway/bff/wstoken.py
# 每会话工作区令牌 = 无状态签名(Fernet 加密 payload)。BFF 铸 / MCP server 解,用同一
# WS_TOKEN_KEY → 跨进程天然互通,**不需共享存储**(修复 BFF/MCP 各自内存 store 不互通)。
# 令牌是 agent→MCP 工具的唯一身份凭证(design「数据集受控链路」,Task0 实证令牌随 URL 抵达)。
# TTL 嵌 payload(exp);撤销 = 进程内 denylist(跨进程靠短 TTL;共享 denylist = v-next)。
from __future__ import annotations

import json
import time
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken


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
    def __init__(self, key: bytes | None = None, ttl_seconds: int = 3600, now=time.time):
        # key=None 仅单实例(测试/单进程)用;跨进程(BFF+MCP)必须传同一 WS_TOKEN_KEY。
        self._f = Fernet(key or Fernet.generate_key())
        self._ttl = ttl_seconds
        self._now = now
        self._revoked: set[str] = set()

    def mint(self, claims: TokenClaims) -> str:
        payload = {"sub": claims.sub, "ent": claims.enterprise, "role": claims.role,
                   "sess": claims.session, "exp": self._now() + self._ttl}
        return self._f.encrypt(json.dumps(payload).encode()).decode()

    def resolve(self, token: str) -> ResolvedToken | None:
        try:
            p = json.loads(self._f.decrypt(token.encode()))   # 验签 + 解密;篡改/错 key → InvalidToken
        except (InvalidToken, ValueError, TypeError):
            return None
        if self._now() >= p.get("exp", 0):                     # 过期(payload exp,now() 可注入)
            return None
        if p.get("sess") in self._revoked:                     # 进程内撤销
            return None
        return ResolvedToken(p["sub"], p["ent"], p["role"], p["sess"])

    def revoke_session(self, session: str) -> int:
        self._revoked.add(session)
        return 1
