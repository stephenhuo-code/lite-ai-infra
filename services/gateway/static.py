from __future__ import annotations
import os
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

_API_PREFIXES = ("/auth", "/v1", "/docs", "/openapi.json", "/redoc", "/healthz")

def install_static(app: FastAPI, dist_dir: str) -> None:
    """gateway serve 前端 dist:/assets 静态 + 其余未知路径回 index.html(SPA fallback)。
    必须在所有 API 路由/反代挂好之后调用(catch-all 最后注册)。API 前缀显式排除不被吞。"""
    if not os.path.isdir(dist_dir):
        return  # dist 未构建 → 不挂,gateway 正常工作
    app.mount("/assets", StaticFiles(directory=os.path.join(dist_dir, "assets")), name="assets")
    index = os.path.join(dist_dir, "index.html")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        if ("/" + full_path).startswith(_API_PREFIXES):
            raise HTTPException(status_code=404, detail="not found")
        return FileResponse(index)
