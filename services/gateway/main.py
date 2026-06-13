# services/gateway/main.py
# 启动:uvicorn services.gateway.main:app --port 8090  (8080 留给 dev Keycloak)
import os

from services.gateway.app import build_gateway

app = build_gateway(routes={
    "/v1/me": os.environ.get("IDENTITY_ORG_URL", "http://localhost:8001"),
    # Plan 4 追加:"/v1/datasets" -> os.environ["METADATA_URL"]
    # Plan 5 追加:"/v1/data"     -> os.environ["DATA_PIPELINE_URL"]
})
