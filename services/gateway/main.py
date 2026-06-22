# services/gateway/main.py
# 启动:uvicorn services.gateway.main:app --port 8090  (8080 留给 dev Keycloak)
# gateway = BFF(ADR-019):服务端 OIDC 登录/会话/登出 + 会话→下游 bearer 注入 + CSRF。
import os

from services._scaffold.app import install_request_id
from services.gateway.app import build_gateway
from services.gateway.bff.middleware import install_bff

# 1) 反代壳(先不加 request-id —— 顺序见下 C-2)
app = build_gateway(routes={
    "/v1/me": os.environ.get("IDENTITY_ORG_URL", "http://localhost:8001"),
    # /v1/catalogs/** 整子树(catalogs/schemas/datasets 导航+CRUD)全转 metadata-service
    "/v1/catalogs": os.environ.get("METADATA_URL", "http://localhost:8002"),
    # /v1/data/** (prepare 提交 + jobs 查状态/列表)全转 data-pipeline-service
    "/v1/data": os.environ.get("DATA_PIPELINE_URL", "http://localhost:8003"),
}, with_request_id=False)

# 2) 挂 BFF:auth 路由(/auth/login·callback·logout)+ /auth/me + 会话/CSRF 中间件。
#    默认 seam(真 KC):exchange_code/refresh_tokens 打 token 端点用 lite-ai-web;
#    /auth/me 解会话内 access 用 LITEAI_JWKS_URL 验签(M-3)。
install_bff(app)

# 3) **C-2 中间件次序(outermost→innermost):request-id → session → proxy routes。**
#    Starlette user_middleware[0]=最外层=最后注册者。按**注册顺序**钉死:
#      build_gateway(with_request_id=False) 未加 request-id
#      → install_bff 加 session 中间件(此刻最外)
#      → install_request_id 最后加 → request-id 最外、session 紧贴反代路由。
#    保证:session 在 call_next 前已设 request.state.bearer(C-1 注入命门);
#    request-id 在最外 → 含 401/403 在内的每个响应都带 x-request-id + 日志。
#    守护测试见 tests/gateway/bff/test_wiring.py(断言两中间件相对次序)。
install_request_id(app)

# 4) serve 前端 dist + SPA history fallback —— catch-all 必须最后挂(否则吞 API)。
#    dist_dir 不存在(纯后端/测试/dev)→ install_static 直接返回、不影响 gateway。
from services.gateway.static import install_static
install_static(app, dist_dir=os.environ.get("FRONTEND_DIST", "frontend/dist"))
