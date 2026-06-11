# spikes/keycloak_org/spike_a.py
"""
Spike A —— Keycloak Organizations/groups token(ADR-010/011 go-no-go)。

验证(本地 compose,Keycloak 26.6.2 --features=organization):
  1. 一个用户属**两个**组 → `groups` claim 带出两条全路径
  2. 改用户子组成员后,**新签发**的 token 多久反映变更(token-stale 窗口)
  3. 已签发旧 token 的 stale 上限 = accessTokenLifespan(从 realm 读出)

跑:make dev-up 后 `uv run python spikes/keycloak_org/spike_a.py`
结论回写 ADR-010。阿里云测试环境需复验一次(同脚本改 KC_BASE)。
"""
from __future__ import annotations
import os, time
import httpx, jwt

KC = os.getenv("KC_BASE", "http://localhost:8080")
REALM = "lite-ai"
ADMIN = f"{KC}/admin/realms/{REALM}"
# dev compose 默认 admin/admin;test 环境密码随机(deploy/test/.env),经 env 覆盖
ADMIN_USER = os.getenv("KC_ADMIN_USER", "admin")
ADMIN_PASSWORD = os.getenv("KC_ADMIN_PASSWORD", "admin")


def admin_token() -> str:
    r = httpx.post(f"{KC}/realms/master/protocol/openid-connect/token",
                   data={"client_id": "admin-cli", "username": ADMIN_USER,
                         "password": ADMIN_PASSWORD, "grant_type": "password"})
    r.raise_for_status()
    return r.json()["access_token"]


def user_token(username: str, password: str) -> dict:
    r = httpx.post(f"{KC}/realms/{REALM}/protocol/openid-connect/token",
                   data={"client_id": "gateway", "client_secret": "dev-secret",
                         "username": username, "password": password,
                         "grant_type": "password"})
    r.raise_for_status()
    return jwt.decode(r.json()["access_token"], options={"verify_signature": False})


def main():
    at = admin_token()
    h = {"Authorization": f"Bearer {at}"}
    c = httpx.Client(headers=h, timeout=10)

    # --- 准备:e-0001 下建第二个组 g-0002/members;建双组用户 bob ---
    groups = c.get(f"{ADMIN}/groups", params={"search": "e-0001"}).json()
    e0001 = next(g for g in groups if g["name"] == "e-0001")
    # 列 e-0001 的子组
    subs = c.get(f"{ADMIN}/groups/{e0001['id']}/children").json()
    g0002 = next((g for g in subs if g["name"] == "g-0002"), None)
    if g0002 is None:
        c.post(f"{ADMIN}/groups/{e0001['id']}/children", json={"name": "g-0002"}).raise_for_status()
        subs = c.get(f"{ADMIN}/groups/{e0001['id']}/children").json()
        g0002 = next(g for g in subs if g["name"] == "g-0002")
    g2subs = c.get(f"{ADMIN}/groups/{g0002['id']}/children").json()
    g2members = next((g for g in g2subs if g["name"] == "members"), None)
    if g2members is None:
        c.post(f"{ADMIN}/groups/{g0002['id']}/children", json={"name": "members"}).raise_for_status()
        g2subs = c.get(f"{ADMIN}/groups/{g0002['id']}/children").json()
        g2members = next(g for g in g2subs if g["name"] == "members")
    # g-0001/members 的 id
    g0001 = next(g for g in subs if g["name"] == "g-0001")
    g1subs = c.get(f"{ADMIN}/groups/{g0001['id']}/children").json()
    g1members = next(g for g in g1subs if g["name"] == "members")

    # 建/重置用户 bob
    existing = c.get(f"{ADMIN}/users", params={"username": "bob", "exact": "true"}).json()
    if existing:
        c.delete(f"{ADMIN}/users/{existing[0]['id']}").raise_for_status()
    c.post(f"{ADMIN}/users", json={
        "username": "bob", "enabled": True, "email": "bob@e-0001.test",
        "emailVerified": True, "firstName": "Bob", "lastName": "Spike",
        "credentials": [{"type": "password", "value": "bob", "temporary": False}],
    }).raise_for_status()
    bob = c.get(f"{ADMIN}/users", params={"username": "bob", "exact": "true"}).json()[0]
    # 加入两个组
    c.put(f"{ADMIN}/users/{bob['id']}/groups/{g1members['id']}").raise_for_status()
    c.put(f"{ADMIN}/users/{bob['id']}/groups/{g2members['id']}").raise_for_status()

    # --- 验证 1:双组全路径 claim ---
    claims = user_token("bob", "bob")
    groups_claim = sorted(claims.get("groups", []))
    print(f"[1] bob 双组 groups claim: {groups_claim}")
    assert groups_claim == ["/e-0001/g-0001/members", "/e-0001/g-0002/members"], "双组全路径断言失败"
    print("    PASS ✓ 两条全路径都在")

    # --- 验证 2:成员变更 → 新 token 反映延迟 ---
    t0 = time.perf_counter()
    c.delete(f"{ADMIN}/users/{bob['id']}/groups/{g2members['id']}").raise_for_status()
    new_claims = user_token("bob", "bob")   # 变更后立刻签新 token
    dt = time.perf_counter() - t0
    new_groups = new_claims.get("groups", [])
    print(f"[2] 移出 g-0002 后 {dt*1000:.0f}ms 签发的新 token groups: {new_groups}")
    assert new_groups == ["/e-0001/g-0001/members"], "新 token 未即时反映变更"
    print("    PASS ✓ 新签发 token 即时反映(无缓存延迟)")

    # --- 验证 3:旧 token stale 上限 = accessTokenLifespan ---
    realm = c.get(f"{ADMIN}").json()
    lifespan = realm.get("accessTokenLifespan")
    exp_window = claims["exp"] - claims["iat"]
    print(f"[3] realm accessTokenLifespan={lifespan}s;实测 token exp-iat={exp_window}s")
    print(f"    结论:已签发旧 token 携带 stale groups 直至过期 → stale 窗口上限 = {exp_window}s")

    print("\nSpike A(本地)全部 PASS。结论待回写 ADR-010;阿里云复验改 KC_BASE 重跑。")


if __name__ == "__main__":
    main()
