# services/_scaffold/proxy.py
from __future__ import annotations

import httpx
from fastapi import FastAPI, Request, Response

# C-1(BFF 命门):**所有客户端可控的鉴权输入都不透传**。bearer 只由 BFF 会话中间件经
# request.state.bearer 注入(见下);客户端自带的 `authorization` **与** `x-test-claims`
# 一律**不读、不转发** —— 二者都是"绕过会话冒充身份"的等价 forge 路径(x-test-claims 在
# 下游 LITEAI_ALLOW_TEST_CLAIMS=1 时会被当真),故 gateway 这道边界统一剥离。
# 测试 seam 仍可**直连下游**注入 x-test-claims(不经 gateway)。gateway 是 mount_proxy 唯一使用者。
_FWD_HEADERS = ("x-request-id", "content-type")


def mount_proxy(app: FastAPI, prefix: str, base_url: str, client_factory=None):
    """把 prefix 下所有方法异步反代到 base_url(保留完整路径、转发 bearer/request-id/body)。
    async 设计:反代是网络 IO,不阻塞 worker;且 in-process ASGI 串联(测试/co-deploy)依赖它。
    client_factory 仅测试注入(ASGITransport + AsyncClient);生产默认真 httpx.AsyncClient(base_url)。"""
    def _factory() -> httpx.AsyncClient:
        if client_factory:
            return client_factory()
        return httpx.AsyncClient(base_url=base_url, timeout=30)

    _METHODS = ["GET", "POST", "PUT", "DELETE", "PATCH"]

    async def _do_forward(request: Request) -> Response:
        fwd_headers = {h: request.headers[h] for h in _FWD_HEADERS if h in request.headers}
        # bearer 唯一来源:BFF 会话中间件设的 request.state.bearer(C-1)。缺失 → 不带任何
        # authorization(让下游 401),**绝不回退客户端原值**。
        bearer = getattr(request.state, "bearer", None)
        if bearer:
            fwd_headers["authorization"] = f"Bearer {bearer}"
        body = await request.body()
        async with _factory() as client:
            up = await client.request(request.method, request.url.path,
                                      params=dict(request.query_params),
                                      headers=fwd_headers, content=body)
        return Response(content=up.content, status_code=up.status_code,
                        media_type=up.headers.get("content-type"))

    # 反代前缀处的集合端点(如 metadata 的 /v1/catalogs):无子路径,需单独匹配,
    # 否则只注册 prefix+"/{path:path}" 会让裸前缀 307/404(子路径仍走下面那条)。
    # include_in_schema=False:gateway 是纯反代壳,通配路由不进自身 openapi
    # (真契约由各服务 contracts/openapi 经聚合 Swagger 暴露);同时消除多方法
    # 通配路由的 Duplicate Operation ID 告警。
    @app.api_route(prefix, methods=_METHODS, include_in_schema=False)
    async def _forward_root(request: Request):
        return await _do_forward(request)

    @app.api_route(prefix + "/{path:path}", methods=_METHODS, include_in_schema=False)
    async def _forward(path: str, request: Request):
        return await _do_forward(request)
