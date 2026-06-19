# services/gateway/app.py
from __future__ import annotations

from fastapi import FastAPI

from services._scaffold.app import make_service_app
from services._scaffold.proxy import mount_proxy


def build_gateway(routes: dict, *, with_request_id: bool = True) -> FastAPI:
    """gateway = BFF 反代壳。routes: {prefix: base_url | (base_url, client_factory)}。
    /docs + /healthz 来自脚手架;业务路由反代到下游(bearer 由 BFF 会话中间件经
    request.state.bearer 注入,下游各自验签;C-1:不透传客户端 bearer)。
    with_request_id=False:main.py 接 BFF 时用 —— 先建反代壳(不含 request-id),
    install_bff 加会话中间件,再 install_request_id 使其最外层(C-2 中间件次序)。"""
    app = make_service_app(title="api-gateway", version="0.1.0", with_request_id=with_request_id)
    for prefix, spec in routes.items():
        base_url, factory = spec if isinstance(spec, tuple) else (spec, None)
        mount_proxy(app, prefix=prefix, base_url=base_url, client_factory=factory)
    return app
