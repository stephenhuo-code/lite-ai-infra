# services/gateway/bff/omnigent_proxy.py
# BFF → omnigent 反代:注入已认证身份头(header-auth),剥离客户端伪造的同名头 + 会话 cookie。
# 安全红线(Task0/ADR-026):omnigent 信任 X-Forwarded-Email,故 BFF MUST 是唯一注入者
# (剥客户端伪造)+ omnigent 不可直达;前端会话 cookie 不外泄给 omnigent。
from __future__ import annotations

_IDENTITY_HEADER = "X-Forwarded-Email"
# 不转发给 omnigent 的客户端头(身份伪造 + 我们的会话凭证)。
_DROP = {"x-forwarded-email", "cookie", "x-csrf-token", "authorization"}


def build_forward_headers(incoming: dict, *, identity_email: str) -> dict:
    out = {k: v for k, v in incoming.items() if k.lower() not in _DROP}
    out[_IDENTITY_HEADER] = identity_email      # 我们注入(唯一来源)
    return out
