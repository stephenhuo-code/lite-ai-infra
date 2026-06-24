# services/identity_org_service/app.py
from fastapi import Depends

from libs.identity.context import Context
from services._scaffold.app import make_service_app
from services._scaffold.auth import context_from_request

app = make_service_app(title="identity-org-service", version="0.1.0")


@app.get("/v1/me/orgs")
def me_orgs(ctx: Context = Depends(context_from_request)):
    return {"user": ctx.user, "is_platform_admin": ctx.is_platform_admin,
            "memberships": [{"enterprise_id": m.enterprise_id, "role": m.role}
                            for m in ctx.memberships]}
