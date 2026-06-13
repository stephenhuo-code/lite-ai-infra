# services/_scaffold/drift.py
from __future__ import annotations

_BUILTIN = {"/docs", "/openapi.json", "/redoc", "/healthz", "/docs/oauth2-redirect"}


def assert_openapi_subset_of_contract(runtime: dict, contract: dict) -> None:
    """运行时暴露的 (path, method) 必须都在契约里声明(内建路径豁免)。
    防"有路由无契约"漂移;schema 字段差异不在此守卫范围(仅告警,见 README)。"""
    c_ops = {(p, m) for p, ms in contract.get("paths", {}).items() for m in ms}
    offenders = []
    for p, ms in runtime.get("paths", {}).items():
        if p in _BUILTIN:
            continue
        for m in ms:
            if (p, m) not in c_ops:
                offenders.append(f"{m.upper()} {p}")
    assert not offenders, f"运行时路由未在契约声明: {offenders}"
