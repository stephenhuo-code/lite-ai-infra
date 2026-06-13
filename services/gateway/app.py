# services/gateway/app.py
from __future__ import annotations

from fastapi import FastAPI

from services._scaffold.app import make_service_app
from services._scaffold.proxy import mount_proxy


def build_gateway(routes: dict) -> FastAPI:
    """gateway = 纯反代壳(BFF)。routes: {prefix: base_url | (base_url, client_factory)}。
    /docs + /healthz 来自脚手架;业务路由全部转发到下游服务(透传 bearer,下游各自验签)。
    v2 可在此加边缘预校验 / 限流 / 聚合。"""
    app = make_service_app(title="api-gateway", version="0.1.0")
    for prefix, spec in routes.items():
        base_url, factory = spec if isinstance(spec, tuple) else (spec, None)
        mount_proxy(app, prefix=prefix, base_url=base_url, client_factory=factory)
    return app
