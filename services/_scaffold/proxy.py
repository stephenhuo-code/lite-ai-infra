# services/_scaffold/proxy.py
from __future__ import annotations

import httpx
from fastapi import FastAPI, Request, Response

_FWD_HEADERS = ("authorization", "x-request-id", "content-type", "x-test-claims")


def mount_proxy(app: FastAPI, prefix: str, base_url: str, client_factory=None):
    """把 prefix 下所有方法异步反代到 base_url(保留完整路径、转发 bearer/request-id/body)。
    async 设计:反代是网络 IO,不阻塞 worker;且 in-process ASGI 串联(测试/co-deploy)依赖它。
    client_factory 仅测试注入(ASGITransport + AsyncClient);生产默认真 httpx.AsyncClient(base_url)。"""
    def _factory() -> httpx.AsyncClient:
        if client_factory:
            return client_factory()
        return httpx.AsyncClient(base_url=base_url, timeout=30)

    @app.api_route(prefix + "/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
    async def _forward(path: str, request: Request):
        fwd_headers = {h: request.headers[h] for h in _FWD_HEADERS if h in request.headers}
        body = await request.body()
        async with _factory() as client:
            up = await client.request(request.method, request.url.path,
                                      params=dict(request.query_params),
                                      headers=fwd_headers, content=body)
        return Response(content=up.content, status_code=up.status_code,
                        media_type=up.headers.get("content-type"))
