# tests/services/identity_org/test_org_directory.py
from services.identity_org_service.org_directory import OrgDirectory


def test_resolves_and_caches():
    calls = []
    d = OrgDirectory(resolver=lambda a: calls.append(a) or f"显示-{a}")
    assert d.display("ent-demo") == "显示-ent-demo"
    assert d.display("ent-demo") == "显示-ent-demo"   # 第二次走缓存
    assert calls == ["ent-demo"]                       # resolver 只调一次


def test_resolver_failure_falls_back_to_none_and_retries():
    calls = []
    def boom(_alias):
        calls.append(_alias)
        raise RuntimeError("kc down")
    d = OrgDirectory(resolver=boom)
    assert d.display("ent-demo") is None               # 失败降级,不抛
    assert d.display("ent-demo") is None               # 失败不缓存 → 下次重试(瞬时 KC 抖动可恢复)
    assert calls == ["ent-demo", "ent-demo"]


def test_legit_none_is_cached():
    # org 无显示名 → 成功解析出 None,应缓存(不每次重打 KC)
    calls = []
    d = OrgDirectory(resolver=lambda a: calls.append(a) or None)
    assert d.display("ent-x") is None
    assert d.display("ent-x") is None
    assert calls == ["ent-x"]                          # 合法 None 入缓存,只解析一次
