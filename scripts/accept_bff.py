"""Plan 6 BFF 一键手动验收(浏览器无关)。`uv run python scripts/accept_bff.py`

会话自举方式同集成测试 test_bff_oidc.py:ROPC(gateway 客户端)拿**真 Keycloak token**
→ 用 SessionCodec(同 dev BFF_SESSION_KEY)构造会话 cookie → 打 **live gateway** 真验:
/auth/me 真验签、/v1/data/jobs(会话→bearer 注入+下游 can())、无会话+伪造 bearer 401(C-1)、
CSRF 缺头 403/带头 202、登出清 cookie。打印 PASS/FAIL,全过退出码 0。

前置:make up(realm 含 lite-ai-web + gateway 带 BFF env)。
注:浏览器视觉登录(/auth/login→Keycloak→回调)是 owner 单独的视觉签认;本脚本覆盖后端实质行为。
env:GW、KC、BFF_SESSION_KEY(默认 = dev_services.sh 的 dev 值)、KC_USER/KC_PASS、GROUP
"""
from __future__ import annotations
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # 仓库根入 path(直接跑)
import httpx
from services.gateway.bff.session import SESSION_COOKIE, SessionCodec, SessionData

GW = os.getenv("GW", "http://localhost:8090")
KC = os.getenv("KC", "http://localhost:8080/realms/lite-ai")
KEY = os.getenv("BFF_SESSION_KEY", "5SetoEInIYji6K_tuQEB8pJ8NCaoC5yi2vNAxtPi7gg=")
USER, PASS = os.getenv("KC_USER", "alice"), os.getenv("KC_PASS", "alice")
GROUP = os.getenv("GROUP", "g-0001")
CSRF = "csrf-accept"

_results: list[tuple[bool, str]] = []
def check(ok: bool, name: str, extra: str = "") -> None:
    _results.append((ok, name)); print(f"  {'✅' if ok else '❌'} {name}{('  — ' + extra) if extra else ''}")

def _ropc_token() -> str:
    r = httpx.post(f"{KC}/protocol/openid-connect/token", timeout=15,
                   data={"client_id": "gateway", "client_secret": "dev-secret",
                         "username": USER, "password": PASS, "grant_type": "password"})
    r.raise_for_status()
    return r.json()["access_token"]

def _session_cookies() -> dict:
    sd = SessionData(_ropc_token(), None, int(time.time()) + 300, csrf=CSRF)
    return {SESSION_COOKIE: SessionCodec(KEY.encode()).encode(sd), "csrf_token": CSRF}

def main() -> int:
    print(f"BFF 验收 @ {GW}(user={USER}, group={GROUP})\n")
    try:
        cookies = _session_cookies()
    except Exception as e:
        check(False, "ROPC 取真 token + 构造会话 cookie", str(e)); return _summary()
    check(True, "会话自举(真 KC token → SessionCodec 加密 cookie)")

    with httpx.Client(base_url=GW, follow_redirects=False, timeout=20, cookies=cookies) as c:
        me = c.get("/auth/me")
        # user = Keycloak sub(平台以 sub 作用户 id;友好名属 backlog #10/S2),非字面 "alice"
        ok_me = me.status_code == 200 and bool(me.json().get("user")) and "csrf" in me.json()
        check(ok_me, "GET /auth/me 真验签返回当前用户(sub)", f"{me.status_code} user={me.json().get('user','')[:12]}…")
        jobs = c.get("/v1/data/jobs")
        check(jobs.status_code == 200, "GET /v1/data/jobs(会话→bearer 注入,经 gateway→下游 can())", f"{jobs.status_code}")
        # catalog-driven 契约(ADR-023):prepare body = {dataset, source_dataset}(去 group_id/tar_dir)。
        body = {"dataset": "accept-probe", "source_dataset": "accept-probe-src"}
        check(c.post("/v1/data/prepare", json=body).status_code == 403, "CSRF 缺 X-CSRF-Token → 403")
        # 带 CSRF 头穿透 BFF 到下游:源未注册则 400(已穿透 + 注入 bearer + 下游解析后拒),
        # 源已注册则 202。两者都证明 CSRF 通过 + 会话注入 bearer 生效(非 BFF 的 403)。
        check(c.post("/v1/data/prepare", json=body, headers={"X-CSRF-Token": CSRF}).status_code in (202, 400),
              "CSRF 带头 → 穿透下游(202 提交 / 400 源未注册;均证 bearer 注入)")
        lo = c.post("/auth/logout", headers={"X-CSRF-Token": CSRF})
        sc = lo.headers.get("set-cookie", "").lower()
        check("session=" in sc and "max-age=0" in sc, "登出清 session cookie(Max-Age=0)", f"{lo.status_code}")

    # C-1 红线:无会话 + 伪造 bearer → 401
    with httpx.Client(base_url=GW, follow_redirects=False, timeout=20) as anon:
        r = anon.get("/v1/data/jobs", headers={"Authorization": "Bearer forged"})
        check(r.status_code == 401, "C-1 红线:无会话 + 伪造 bearer → 401(不绕过)", f"{r.status_code}")
    return _summary()

def _summary() -> int:
    passed = sum(1 for ok, _ in _results if ok)
    print(f"\n{'='*48}\n{passed}/{len(_results)} 通过", end="")
    failed = [n for ok, n in _results if not ok]
    if failed:
        print("  ❌ 失败:" + "; ".join(failed)); return 1
    print("  ✅ 全部通过(Plan 6 BFF 后端验收)"); return 0

if __name__ == "__main__":
    sys.exit(main())
