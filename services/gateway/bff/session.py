# services/gateway/bff/session.py —— BFF 无状态会话(ADR-019)
# 会话 = Fernet 对称加密的 cookie(v1 无 PG;规避 Redis 取舍,置会话存储 seam,v2 可换)。
# 装 {access, refresh, exp, csrf};中间件解密 → 注入下游 bearer(Task 5)。
# Task 1 实测:{access+refresh+exp+csrf} 密文 ~2560B < 4KB 单 cookie 上限(probe.md §3);
# 若未来用户组数使 cookie >4KB → 降级(只存 refresh / 拆 cookie),此处是唯一改点。
from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from cryptography.fernet import Fernet, InvalidToken


@dataclass
class SessionData:
    access_token: str
    refresh_token: str | None
    expires_at: int                       # epoch 秒(access token 过期点)
    csrf: str = ""                        # 双提交 CSRF token(登录回调一次生成,Task 4/6;与明文 csrf_token cookie 同值)

    def is_expired(self, now: int, skew: int = 30) -> bool:
        # skew:提前 30s 视为过期,留刷新窗口(避免 access 刚好在下游验签时过期)
        return now >= self.expires_at - skew


class SessionCodec:
    """Fernet 对称加密 JSON 会话。key 从 env(BFF_SESSION_KEY);decode 容错返 None
    (篡改 / 错 key / 过期 Fernet TTL / 坏 JSON 一律 None → 中间件按未登录处理)。"""

    def __init__(self, key: bytes):
        self._f = Fernet(key)

    def encode(self, s: SessionData) -> str:
        return self._f.encrypt(json.dumps(asdict(s)).encode()).decode()

    def decode(self, token: str) -> SessionData | None:
        try:
            return SessionData(**json.loads(self._f.decrypt(token.encode())))
        except (InvalidToken, ValueError, TypeError):
            return None
