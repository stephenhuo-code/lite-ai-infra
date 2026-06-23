from __future__ import annotations
import os
import httpx


class MetadataClient:
    """data-pipeline → metadata 只读:按名解析数据集(带用户 bearer,经 metadata can())。"""

    def __init__(self, base_url: str | None = None, transport=None):
        self._c = httpx.Client(
            base_url=base_url or os.environ.get("METADATA_URL", "http://localhost:8002"),
            timeout=15, transport=transport)

    def get_dataset(self, catalog: str, schema: str, name: str, *, bearer: str) -> dict:
        r = self._c.get(
            f"/v1/catalogs/{catalog}/schemas/{schema}/datasets/{name}",
            headers={"Authorization": bearer} if bearer else {})
        r.raise_for_status()
        return r.json()
