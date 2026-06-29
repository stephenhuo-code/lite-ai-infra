#!/usr/bin/env python3
"""幂等置备 KC Organizations(企业)——dev/prod 重导/迁移都可重复跑。

做五件事(每步查重幂等,见 ADR-025 / spike RESULTS):
  ① 建/取 org(by 不透明 alias `ent-demo`,设 domains + display_name attribute);
  ② 把现有 realm 用户(alice 等,by username)以 **UNMANAGED** 加入 org(已是成员则跳,保账号 F4);
  ③ 把 `organization` client scope 设为相关 client 的 **default** scope(多-org `organization:*` 前置,F3);
  ④ 移除旧 `/e-XXXX/g-YYYY/` 子组(存在才删,身份降两级,清理 group 维度)。

token 用 master/admin-cli(admin/admin)direct-grant 拿。仅置备,不做授权决策。
逻辑都在 KCAdmin 方法上(transport 可注入)→ 见 tests/identity/test_provision_orgs.py 契约级幂等测试。
用法:`uv run python scripts/provision_orgs.py`(env 可覆盖 KC_BASE_URL / KC_ADMIN_USER / KC_ADMIN_PASSWORD)。
"""
from __future__ import annotations

import os
import sys

import httpx

REALM = "lite-ai"
# dev 默认置备目标(prod 经 env / 参数覆盖)。alias 不透明,不复用人工 e-XXXX。
ORG_ALIAS = "ent-demo"
ORG_NAME = "Demo"
ORG_DOMAINS = ["acme.test"]
ORG_DISPLAY_NAME = "Demo 企业"
MEMBER_USERNAMES = ["alice", "bob"]  # bob = 第二测试用户(Plan 9a 双用户隔离验收;plain member)
# dev 测试用户(幂等 ensure):realm 导入只在 KC 库空时发生,已存在 realm 再起 KC **不会**补进新用户。
# 故这里经 Admin API 幂等补建 —— realm json 仍是首次导入的真相源,这只保证 ws-up 在持久化的 KC 库上也能拿到 bob。
# (username, email, password, realm_roles)
TEST_USERS = [
    ("alice", "alice@acme.test", "alice", ["enterprise-admin"]),
    ("bob", "bob@acme.test", "bob", []),
]
# 加 organization scope 为 default 的 client(BFF 走 lite-ai-web;direct-grant 走 gateway)。
SCOPE_CLIENTS = ["lite-ai-web", "gateway"]
# 旧两级 group 维度(身份降两级后移除);存在才删。
LEGACY_ENTERPRISE_GROUPS = ["e-0001"]


class KCAdmin:
    """KC Admin REST 薄客户端(组织/成员/scope/group)。transport 仅测试注入。"""

    def __init__(self, base_url: str, token: str = "", transport: httpx.BaseTransport | None = None):
        self.realm = REALM
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._c = httpx.Client(base_url=base_url.rstrip("/"), headers=headers, timeout=30, transport=transport)

    def close(self) -> None:
        self._c.close()

    # --- low-level ---
    def _ok(self, r: httpx.Response) -> httpx.Response:
        if r.status_code >= 300:
            raise RuntimeError(f"KC admin {r.request.method} {r.request.url} -> {r.status_code} {r.text}")
        return r

    def _get(self, path: str, **kw) -> httpx.Response:
        return self._ok(self._c.get(path, **kw))

    def _r(self, realm_path: str) -> str:
        return f"/admin/realms/{self.realm}{realm_path}"

    # --- ① org ---
    def find_org(self, alias: str) -> dict | None:
        # KC `/organizations?search=` 按 name/domain 匹配,**不匹配 alias** → 用 alias 搜会漏掉
        # name 不同的已存在 org(如 realm 导入的 alias=ent-demo/name=Demo)→ 误判不存在 → 重建 409。
        # 故列全量(dev 规模可忽略分页)按 alias 精确过滤。
        orgs = self._get(self._r("/organizations"), params={"first": 0, "max": 1000}).json()
        for o in orgs:
            if o.get("alias") == alias:
                return o
        return None

    def ensure_org(self, *, alias: str, name: str, domains: list[str], display_name: str) -> str:
        existing = self.find_org(alias)
        if existing:
            return existing["id"]
        body = {
            "name": name, "alias": alias, "enabled": True,
            "domains": [{"name": d, "verified": True} for d in domains],
            "attributes": {"display_name": [display_name]},
        }
        self._ok(self._c.post(self._r("/organizations"), json=body))
        created = self.find_org(alias)
        if not created:
            raise RuntimeError(f"org {alias} 创建后仍查不到")
        return created["id"]

    # --- ②a 测试用户幂等补建(持久化 KC 库上 realm 不再重导时兜底)---
    def ensure_user(self, *, username: str, email: str, password: str,
                    realm_roles: list[str] | None = None) -> bool:
        """已存在(by username)→ 不建,返回 False;缺失 → 建(emailVerified + 固定密码 + realm 角色),返回 True。"""
        if self.find_user_id(username) is not None:
            return False
        body = {
            "username": username, "email": email, "enabled": True, "emailVerified": True,
            "firstName": username.capitalize(), "lastName": "Test",
            "credentials": [{"type": "password", "value": password, "temporary": False}],
        }
        self._ok(self._c.post(self._r("/users"), json=body))
        uid = self.find_user_id(username)
        if uid is None:
            raise RuntimeError(f"user {username} 创建后仍查不到")
        for role in realm_roles or []:
            rep = self._get(self._r(f"/roles/{role}")).json()
            self._ok(self._c.post(self._r(f"/users/{uid}/role-mappings/realm"),
                                  json=[{"id": rep["id"], "name": rep["name"]}]))
        return True

    # --- ② members(UNMANAGED) ---
    def find_user_id(self, username: str) -> str | None:
        users = self._get(self._r("/users"), params={"username": username, "exact": "true"}).json()
        return users[0]["id"] if users else None

    def org_member_ids(self, org_id: str) -> set[str]:
        members = self._get(self._r(f"/organizations/{org_id}/members")).json()
        return {m["id"] for m in members}

    def ensure_member(self, org_id: str, username: str) -> bool:
        """把现有用户以 UNMANAGED 加入 org。已是成员/无此用户 → 不 POST,返回 False。"""
        uid = self.find_user_id(username)
        if uid is None:
            return False
        if uid in self.org_member_ids(org_id):
            return False
        # KC 26:POST organizations/{id}/members,body = 裸 user id(加入存量用户=UNMANAGED,保账号)。
        self._ok(self._c.post(self._r(f"/organizations/{org_id}/members"), content=uid,
                              headers={"Content-Type": "application/json"}))
        return True

    # --- ③ organization scope 设为 client default ---
    def find_client_id(self, client_id: str) -> str | None:
        clients = self._get(self._r("/clients"), params={"clientId": client_id}).json()
        return clients[0]["id"] if clients else None

    def find_client_scope_id(self, name: str) -> str | None:
        for s in self._get(self._r("/client-scopes")).json():
            if s.get("name") == name:
                return s["id"]
        return None

    def ensure_default_scope(self, client_id: str, scope_name: str = "organization") -> bool:
        cid = self.find_client_id(client_id)
        sid = self.find_client_scope_id(scope_name)
        if cid is None or sid is None:
            return False
        # PUT 幂等:已是 default 则重复 PUT 无副作用。
        self._ok(self._c.put(self._r(f"/clients/{cid}/default-client-scopes/{sid}")))
        return True

    # --- ④ 移除旧两级 group 维度 ---
    def remove_legacy_group(self, name: str) -> bool:
        for g in self._get(self._r("/groups"), params={"search": name}).json():
            if g.get("name") == name:
                self._ok(self._c.delete(self._r(f"/groups/{g['id']}")))
                return True
        return False

    # --- ⑤ 禁用 Organizations 自带 identity-first 登录步(回到用户名+密码同页)---
    def disable_org_identity_first(self, flow: str = "browser") -> bool:
        # organizationsEnabled 后 KC 内置 browser flow 会加 "Organization Identity-First Login"
        # (先输用户名的两步式)。v1 不用 per-org IdP,禁它 → 落到 Username Password Form(同页)。
        # 幂等:已 DISABLED 则跳过。dev-reset 重导后由本脚本恢复。
        for e in self._get(self._r(f"/authentication/flows/{flow}/executions")).json():
            if (e.get("displayName") or "").strip() == "Organization Identity-First Login":
                if e.get("requirement") == "DISABLED":
                    return False
                self._ok(self._c.put(self._r(f"/authentication/flows/{flow}/executions"),
                                     json={"id": e["id"], "requirement": "DISABLED"}))
                return True
        return False


def admin_token(base_url: str, user: str, password: str) -> str:
    r = httpx.post(f"{base_url.rstrip('/')}/realms/master/protocol/openid-connect/token",
                   data={"client_id": "admin-cli", "grant_type": "password",
                         "username": user, "password": password}, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def provision(kc: KCAdmin) -> dict:
    """跑全部置备步骤,返回大白话摘要(供 runbook 打印)。"""
    org_id = kc.ensure_org(alias=ORG_ALIAS, name=ORG_NAME, domains=ORG_DOMAINS, display_name=ORG_DISPLAY_NAME)
    users_created = [u for (u, e, p, r) in TEST_USERS
                     if kc.ensure_user(username=u, email=e, password=p, realm_roles=r)]
    added = [u for u in MEMBER_USERNAMES if kc.ensure_member(org_id, u)]
    scoped = [c for c in SCOPE_CLIENTS if kc.ensure_default_scope(c)]
    removed = [g for g in LEGACY_ENTERPRISE_GROUPS if kc.remove_legacy_group(g)]
    idf_disabled = kc.disable_org_identity_first()
    return {"org_id": org_id, "users_created": users_created, "members_added": added,
            "scoped_clients": scoped, "legacy_groups_removed": removed,
            "identity_first_disabled": idf_disabled}


def main() -> int:
    base = os.getenv("KC_BASE_URL", "http://localhost:8080")
    user = os.getenv("KC_ADMIN_USER", "admin")
    pw = os.getenv("KC_ADMIN_PASSWORD", "admin")
    kc = KCAdmin(base_url=base, token=admin_token(base, user, pw))
    try:
        s = provision(kc)
    finally:
        kc.close()
    print(f"org `{ORG_ALIAS}` 就绪(id={s['org_id']})")
    print(f"  新建测试用户:{s['users_created'] or '无(已全部存在)'}")
    print(f"  新加入成员(UNMANAGED):{s['members_added'] or '无(已全部是成员)'}")
    print(f"  organization scope 已设为 default 的 client:{s['scoped_clients'] or '无'}")
    print(f"  已移除的旧 group 维度:{s['legacy_groups_removed'] or '无(已清理)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
