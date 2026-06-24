# services/identity_org_service/org_directory.py
# 企业显示名解析(FR-002b):token 只带 org alias(spike RESULTS F1);显示名是 org 属性,
# 经 KC admin REST 读,按 alias 进程内缓存(orgs 变动稀少)。任何失败 → None(界面回退 alias),
# 绝不阻塞 /v1/me/orgs。resolver 仅测试注入。dev 默认连 localhost:8080 admin/admin(与置备脚本一致);
# prod 经 env(KC_BASE_URL / KC_ADMIN_USER / KC_ADMIN_PASSWORD / KC_REALM)注入真凭据(§5.2)。
from __future__ import annotations

import os
from collections.abc import Callable

import httpx


class OrgDirectory:
    """alias → 企业显示名解析器 + 进程内缓存。resolver(alias)->str|None 仅测试注入。"""

    def __init__(self, resolver: Callable[[str], str | None] | None = None):
        self._resolver = resolver if resolver is not None else _kc_lookup
        self._cache: dict[str, str | None] = {}

    def display(self, alias: str) -> str | None:
        if alias in self._cache:           # 命中:含"org 无显示名"的合法 None(已成功解析过)
            return self._cache[alias]
        try:
            self._cache[alias] = self._resolver(alias)   # 仅成功解析才入缓存
        except Exception:
            return None                    # 降级:解析失败不缓存(下次重试)、不阻塞,界面回退 alias
        return self._cache[alias]


def _kc_lookup(alias: str) -> str | None:
    """读 KC org 属性里的显示名(admin REST)。失败抛异常由 OrgDirectory 兜底为 None。"""
    base = os.getenv("KC_BASE_URL", "http://localhost:8080").rstrip("/")
    user = os.getenv("KC_ADMIN_USER", "admin")
    pw = os.getenv("KC_ADMIN_PASSWORD", "admin")
    realm = os.getenv("KC_REALM", "lite-ai")
    tok = httpx.post(f"{base}/realms/master/protocol/openid-connect/token",
                     data={"client_id": "admin-cli", "grant_type": "password",
                           "username": user, "password": pw}, timeout=5).json()["access_token"]
    orgs = httpx.get(f"{base}/admin/realms/{realm}/organizations", params={"search": alias},
                     headers={"Authorization": f"Bearer {tok}"}, timeout=5).json()
    for o in orgs:
        if o.get("alias") == alias:
            dn = (o.get("attributes") or {}).get("display_name")  # display-name-ok(KC org 属性键)
            if isinstance(dn, list):
                return dn[0] if dn else None
            return dn or None
    return None
