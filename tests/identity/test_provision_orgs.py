# tests/identity/test_provision_orgs.py
# 契约级:对 KC admin REST 的 httpx 做 MockTransport,断言 provision_orgs 幂等
# ——org/成员已存在则不重复 POST,缺失则建。不触真 KC。
import httpx
import pytest

from scripts.provision_orgs import KCAdmin


def _admin(handler):
    return KCAdmin(base_url="http://kc", token="t", transport=httpx.MockTransport(handler))


# ---- ensure_org 幂等 ----

def test_ensure_org_exists_no_post():
    posts = []

    def h(req):
        if req.method == "GET" and req.url.path.endswith("/organizations"):
            return httpx.Response(200, json=[{"id": "org-1", "alias": "ent-demo", "name": "Demo"}])
        if req.method == "POST":
            posts.append(str(req.url))
            return httpx.Response(201)
        raise AssertionError(f"unexpected {req.method} {req.url}")

    oid = _admin(h).ensure_org(alias="ent-demo", name="Demo", domains=["acme.test"], display_name="Demo 企业")
    assert oid == "org-1"
    assert posts == []  # 已存在 → 不建


def test_ensure_org_found_via_list_not_search():
    # 回归:KC 真实语义 `/organizations?search=<alias>` 只匹配 name/domain、**不匹配 alias** → 返回空;
    # 必须列全量(无 search)才能按 alias 找到 realm 导入的 org(name=Demo/alias=ent-demo)。
    # 守护 find_org 不靠 search 匹配 alias(否则误判不存在 → 重建 → 真 KC 409)。
    posts = []

    def h(req):
        if req.method == "GET" and req.url.path.endswith("/organizations"):
            if "search" in req.url.params:
                return httpx.Response(200, json=[])  # KC search 漏掉 alias
            return httpx.Response(200, json=[{"id": "org-1", "alias": "ent-demo", "name": "Demo"}])
        if req.method == "POST":
            posts.append(str(req.url))
            return httpx.Response(409, json={"errorMessage": "A organization with the same name already exists."})
        raise AssertionError(f"unexpected {req.method} {req.url}")

    oid = _admin(h).ensure_org(alias="ent-demo", name="Demo", domains=["acme.test"], display_name="Demo 企业")
    assert oid == "org-1"
    assert posts == []  # 靠列全量找到 → 不重建、不触 409


def test_ensure_org_missing_creates():
    state = {"created": False}
    posts = []

    def h(req):
        if req.method == "GET" and req.url.path.endswith("/organizations"):
            if state["created"]:
                return httpx.Response(200, json=[{"id": "org-9", "alias": "ent-demo", "name": "Demo"}])
            return httpx.Response(200, json=[])
        if req.method == "POST" and req.url.path.endswith("/organizations"):
            posts.append(req.read().decode())
            state["created"] = True
            return httpx.Response(201, headers={"Location": "http://kc/.../organizations/org-9"})
        raise AssertionError(f"unexpected {req.method} {req.url}")

    oid = _admin(h).ensure_org(alias="ent-demo", name="Demo", domains=["acme.test"], display_name="Demo 企业")
    assert oid == "org-9"
    assert len(posts) == 1
    body = posts[0]
    assert "ent-demo" in body and "acme.test" in body and "Demo 企业" in body


# ---- ensure_member 幂等(unmanaged) ----

def test_ensure_member_exists_no_post():
    posts = []

    def h(req):
        p = req.url.path
        if req.method == "GET" and p.endswith("/users"):
            return httpx.Response(200, json=[{"id": "u-alice", "username": "alice"}])
        if req.method == "GET" and p.endswith("/members"):
            return httpx.Response(200, json=[{"id": "u-alice", "username": "alice"}])
        if req.method == "POST":
            posts.append(p)
            return httpx.Response(201)
        raise AssertionError(f"unexpected {req.method} {req.url}")

    added = _admin(h).ensure_member("org-1", "alice")
    assert added is False
    assert posts == []


def test_ensure_member_missing_adds_unmanaged():
    posts = []

    def h(req):
        p = req.url.path
        if req.method == "GET" and p.endswith("/users"):
            return httpx.Response(200, json=[{"id": "u-alice", "username": "alice"}])
        if req.method == "GET" and p.endswith("/members"):
            return httpx.Response(200, json=[])
        if req.method == "POST" and p.endswith("/members"):
            posts.append(req.read().decode())
            return httpx.Response(201)
        raise AssertionError(f"unexpected {req.method} {req.url}")

    added = _admin(h).ensure_member("org-1", "alice")
    assert added is True
    assert len(posts) == 1
    assert "u-alice" in posts[0]  # 以 user id 作 body 加入(UNMANAGED,保账号)


def test_ensure_member_unknown_user_skips():
    posts = []

    def h(req):
        p = req.url.path
        if req.method == "GET" and p.endswith("/users"):
            return httpx.Response(200, json=[])  # 无此用户
        if req.method == "POST":
            posts.append(p)
            return httpx.Response(201)
        return httpx.Response(200, json=[])

    added = _admin(h).ensure_member("org-1", "ghost")
    assert added is False
    assert posts == []
