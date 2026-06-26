# services/gateway/bff/workspace.py
# BFF 工作区会话端点:建 omnigent 会话 → 铸每会话令牌 → 注册我们的 MCP server(令牌化 URL)。
# 安全:从【已认证的 BFF 会话】取身份(sub/企业/角色),绝不信任请求里的身份头 —— 反代层 MUST
# 先剥离客户端传入的 X-Forwarded-Email(strip_forged_identity_headers)。
# Task0 实证:omnigent 按注册 URL 原样连、令牌随 URL 抵达我们的 MCP server。
from __future__ import annotations

from services.gateway.bff.omnigent_client import OmnigentClient
from services.gateway.bff.wstoken import TokenClaims, WorkspaceTokenStore

_FORGED = ("x-forwarded-email",)   # 客户端不得自带的信任头(反代入口剥离)


def strip_forged_identity_headers(headers: dict) -> dict:
    return {k: v for k, v in headers.items() if k.lower() not in _FORGED}


def create_workspace_session(*, sub: str, enterprise: str, role: str, agent_id: str,
                             store: WorkspaceTokenStore, omni: OmnigentClient,
                             mcp_base_url: str) -> dict:
    sid = omni.create_session(agent_id=agent_id)
    tok = store.mint(TokenClaims(sub=sub, enterprise=enterprise, role=role, session=sid))
    omni.register_mcp(session_id=sid, name="liteai",
                      url=f"{mcp_base_url.rstrip('/')}/s/{tok}/mcp")
    return {"session_id": sid}     # 令牌不回给前端(前端不持令牌,经 BFF 反代)
