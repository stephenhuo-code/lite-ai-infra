# services/identity_org_service/app.py
from fastapi import Depends

from libs.identity.context import Context
from services._scaffold.app import make_service_app
from services._scaffold.auth import context_from_request
from services.identity_org_service.org_directory import OrgDirectory

app = make_service_app(title="identity-org-service", version="0.1.0")

# 企业显示名解析器(FR-002b);测试经 monkeypatch 注入假 resolver。
_ORG_DIR = OrgDirectory()


@app.get("/v1/me/orgs")
def me_orgs(ctx: Context = Depends(context_from_request)):
    # 身份降两级:memberships 只含 enterprise_id/role(无访问组)。
    # enterprises:去重的企业 + 显示名(界面渲染,§1.4 不透明 alias 绝不渲染)。
    aliases: list[str] = []
    for m in ctx.memberships:
        if m.enterprise_id not in aliases:
            aliases.append(m.enterprise_id)
    return {"user": ctx.user, "is_platform_admin": ctx.is_platform_admin,
            "memberships": [{"enterprise_id": m.enterprise_id, "role": m.role}
                            for m in ctx.memberships],
            "enterprises": [{"alias": a, "display_name": _ORG_DIR.display(a)}  # display-name-ok(界面渲染,FR-002b)
                            for a in aliases]}
