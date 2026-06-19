# services/_scaffold/app.py
from __future__ import annotations
import logging, uuid

from fastapi import FastAPI, Request

log = logging.getLogger("svc")


def install_request_id(app: FastAPI) -> None:
    """request-id + 结构化日志中间件。抽成独立函数:gateway BFF 需把它**显式最后注册**
    (=最外层)以包住会话中间件(ADR-019 C-2:request-id 外层 / session 内层)。"""
    @app.middleware("http")
    async def _request_id(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        log.info("req", extra={"rid": rid, "path": request.url.path, "method": request.method})
        response = await call_next(request)
        response.headers["x-request-id"] = rid
        return response


def make_service_app(title: str, version: str, *, with_request_id: bool = True) -> FastAPI:
    """所有服务的统一 app 工厂:/docs + /openapi.json(FastAPI 自带)、/healthz、
    request-id + 结构化日志中间件。各服务模块级 `app = make_service_app(...)`。
    with_request_id=False:由调用方稍后 install_request_id(顺序敏感场景,如 gateway BFF 中间件栈)。"""
    app = FastAPI(title=title, version=version)

    if with_request_id:
        install_request_id(app)

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    return app
