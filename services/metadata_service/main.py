# 启动:uvicorn services.metadata_service.main:app --port 8002
#   需 env:GRAVITINO_URL(默认 http://localhost:8091);LITEAI_JWKS_URL(生产验签)
import os

from services.metadata_service.app import build_app
from services.metadata_service.gravitino import GravitinoClient

app = build_app(gravitino=GravitinoClient(base_url=os.environ.get("GRAVITINO_URL", "http://localhost:8091")))
