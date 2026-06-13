# services/identity_org_service/main.py
# 启动:uvicorn services.identity_org_service.main:app --port 8001
#   需 env:LITEAI_JWKS_URL(生产验签);LITEAI_TOKEN_ISSUER/AUDIENCE 可选
from services.identity_org_service.app import app  # noqa: F401
