# services/gateway/bff/orgs.py
# 企业邀请:经 KC admin REST 邀请用户入 org(by alias → id → invite-user;spike RESULTS F6)。
# 仅 BFF 邀请端点(enterprise-admin)调用。admin 凭据经 env 注入(§5.2);transport 仅测试注入。
from __future__ import annotations

import os

import httpx


class OrgInviteError(RuntimeError):
    """org 未找到 / KC 邀请失败。"""


class OrgInviter:
    """KC org 邀请客户端。dev 默认连 localhost:8080 admin/admin(与置备脚本一致);
    prod 经 env(KC_BASE_URL / KC_ADMIN_USER / KC_ADMIN_PASSWORD / KC_REALM)注入真凭据。"""

    def __init__(self, *, base_url: str | None = None, admin_user: str | None = None,
                 admin_password: str | None = None, realm: str | None = None,
                 transport: httpx.BaseTransport | None = None):
        self._base = (base_url or os.getenv("KC_BASE_URL", "http://localhost:8080")).rstrip("/")
        self._user = admin_user or os.getenv("KC_ADMIN_USER", "admin")
        self._pw = admin_password or os.getenv("KC_ADMIN_PASSWORD", "admin")
        self._realm = realm or os.getenv("KC_REALM", "lite-ai")
        self._transport = transport

    def _client(self, token: str = "") -> httpx.Client:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return httpx.Client(base_url=self._base, headers=headers, timeout=10, transport=self._transport)

    def _admin_token(self) -> str:
        with self._client() as c:
            r = c.post("/realms/master/protocol/openid-connect/token",
                       data={"client_id": "admin-cli", "grant_type": "password",
                             "username": self._user, "password": self._pw})
            r.raise_for_status()
            return r.json()["access_token"]

    def invite(self, org_alias: str, email: str) -> None:
        """邀请 email 入 org(by alias)。org 不存在或 KC 失败 → OrgInviteError。"""
        token = self._admin_token()
        with self._client(token) as c:
            orgs = c.get(f"/admin/realms/{self._realm}/organizations", params={"search": org_alias})
            orgs.raise_for_status()
            org = next((o for o in orgs.json() if o.get("alias") == org_alias), None)
            if org is None:
                raise OrgInviteError(f"org not found: {org_alias}")
            # KC 26:form email/firstName/lastName(F6 实测端点)。dev 需 SMTP(mailpit)发邮件。
            r = c.post(f"/admin/realms/{self._realm}/organizations/{org['id']}/members/invite-user",
                       data={"email": email})
            if r.status_code >= 300:
                raise OrgInviteError(f"invite failed: {r.status_code} {r.text}")
