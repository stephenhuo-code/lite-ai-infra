# services/_scaffold/app.py
from __future__ import annotations
import logging, uuid

from fastapi import FastAPI, Request

log = logging.getLogger("svc")


def make_service_app(title: str, version: str) -> FastAPI:
    """所有服务的统一 app 工厂:/docs + /openapi.json(FastAPI 自带)、/healthz、
    request-id + 结构化日志中间件。各服务模块级 `app = make_service_app(...)`。"""
    app = FastAPI(title=title, version=version)

    @app.middleware("http")
    async def _request_id(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        log.info("req", extra={"rid": rid, "path": request.url.path, "method": request.method})
        response = await call_next(request)
        response.headers["x-request-id"] = rid
        return response

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    return app
