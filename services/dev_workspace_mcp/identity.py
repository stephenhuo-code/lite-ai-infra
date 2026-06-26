# services/dev_workspace_mcp/identity.py
# 令牌 → Context(与控制台后端同形,复用 Membership/EnterpriseId)。当前会话令牌用 contextvar
# 承载(FastMCP 工具函数从此读 ctx)。fail-closed:令牌无效 → None,工具按 deny 处理。
from __future__ import annotations

import contextvars

from libs.identity.context import Context, Membership
from libs.identity.ids import EnterpriseId
from services.gateway.bff.wstoken import WorkspaceTokenStore

_token: contextvars.ContextVar[str | None] = contextvars.ContextVar("ws_token", default=None)
_store: contextvars.ContextVar[WorkspaceTokenStore | None] = contextvars.ContextVar("ws_store", default=None)


def context_from_token(store: WorkspaceTokenStore, token: str) -> Context | None:
    r = store.resolve(token)
    if r is None:
        return None
    return Context(user=r.sub,
                   memberships=[Membership(EnterpriseId(r.enterprise), r.role)],
                   is_platform_admin=False)   # 工作区会话不走平台管理员特权


def set_current_token(store: WorkspaceTokenStore, token: str) -> None:
    _store.set(store)
    _token.set(token)


def current_context() -> Context | None:
    s, t = _store.get(), _token.get()
    return context_from_token(s, t) if (s and t) else None
