# services/gateway/bff/credentials_routes.py
# 订阅凭据 onboarding(Dev Workspace,T5):用户在设置页提交自己的 claude / codex 订阅凭据,
# 产品加密存(CredentialVault,T4),后续注入该用户的 omnigent host 容器。
# 身份取自【已认证 BFF 会话】(同 workspace_routes 的 _resolve),user_id = ctx.user。
# 安全红线:secret 只入 vault,绝不回显 / 落日志;POST 成功仅回 {"ok": true}。
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from services.credential_vault.vault import CredentialVault
from services.gateway.bff.workspace_routes import _resolve

_PROVIDERS = ("claude", "codex")


def make_credentials_router(*, claims, vault: CredentialVault) -> APIRouter:
    router = APIRouter()

    @router.get("/v1/me/model-credentials")
    def status(request: Request):
        ident, err = _resolve(request, claims)
        if err:
            return err
        ctx, _enterprise, _role, _email = ident
        return vault.status(user_id=ctx.user)

    @router.post("/v1/me/model-credentials")
    async def put(request: Request):
        ident, err = _resolve(request, claims)
        if err:
            return err
        ctx, _enterprise, _role, _email = ident
        body = await request.json()
        provider = (body or {}).get("provider", "")
        secret = (body or {}).get("secret", "")
        if provider not in _PROVIDERS:
            raise HTTPException(status_code=400, detail="unknown provider")
        if not secret:
            raise HTTPException(status_code=400, detail="secret required")
        vault.put(user_id=ctx.user, provider=provider, secret=secret)
        return {"ok": True}                    # 绝不回显 secret

    @router.delete("/v1/me/model-credentials/{provider}")
    def delete(provider: str, request: Request):
        ident, err = _resolve(request, claims)
        if err:
            return err
        ctx, _enterprise, _role, _email = ident
        if provider not in _PROVIDERS:
            raise HTTPException(status_code=400, detail="unknown provider")
        vault.delete(user_id=ctx.user, provider=provider)
        return {"ok": True}

    return router
