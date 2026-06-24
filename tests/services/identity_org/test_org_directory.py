# tests/services/identity_org/test_org_directory.py
from services.identity_org_service.org_directory import OrgDirectory


def test_resolves_and_caches():
    calls = []
    d = OrgDirectory(resolver=lambda a: calls.append(a) or f"显示-{a}")
    assert d.display("ent-demo") == "显示-ent-demo"
    assert d.display("ent-demo") == "显示-ent-demo"   # 第二次走缓存
    assert calls == ["ent-demo"]                       # resolver 只调一次


def test_resolver_failure_falls_back_to_none():
    def boom(_alias):
        raise RuntimeError("kc down")
    d = OrgDirectory(resolver=boom)
    assert d.display("ent-demo") is None               # 失败降级,不抛
    assert d.display("ent-demo") is None               # 缓存 None,不重试风暴
