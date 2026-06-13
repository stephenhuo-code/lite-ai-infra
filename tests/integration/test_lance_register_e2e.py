# tests/integration/test_lance_register_e2e.py
import json
import uuid

import lance
import pyarrow as pa
import pytest
from fastapi.testclient import TestClient

from pipelines.data_prep.lance_writer import lance_storage_options
from services.metadata_service.app import build_app
from services.metadata_service.gravitino import GravitinoClient

pytestmark = pytest.mark.integration

# Gravitino 容器内经别名访问 MinIO;catalog schema 位置校验需该 bucket 先存在。
_GRAVITINO_S3_ENDPOINT = "http://minio:9000"
_CATALOG_BUCKET = "lite-ai-dev"


def _ensure_tree(g, minio_s3):
    if _CATALOG_BUCKET not in [b["Name"] for b in minio_s3.list_buckets()["Buckets"]]:
        minio_s3.create_bucket(Bucket=_CATALOG_BUCKET)
    g.ensure_metalake("e_0001")
    g.ensure_catalog("e_0001", "data", bucket=_CATALOG_BUCKET,
                     s3_endpoint=_GRAVITINO_S3_ENDPOINT, access_key="minio", secret_key="minio123")
    g.ensure_schema("e_0001", "data", "datasets")


def test_lance_create_then_register(minio_s3, minio_bucket, gravitino_url, monkeypatch):
    """串 Plan 2/4:MinIO 建真 Lance → metadata-service 注册 → 查回 → 读回验证。
    scheme 二元性:同一物理对象,lance 读写用 s3://(object_store),Gravitino location 记 s3a://(HCFS)。"""
    monkeypatch.setenv("LITEAI_ALLOW_TEST_CLAIMS", "1")
    n = f"ds_{uuid.uuid4().hex[:6]}"

    # 1) MinIO 上建真 Lance 数据集(lance 用 s3://)
    opts = lance_storage_options("http://localhost:9000", minio_bucket, "minio", "minio123", region="us-east-1")
    uri = f"s3://{minio_bucket}/e-0001/g-0001/processed/{n}.lance"
    lance.write_dataset(pa.table({"text": ["a", "b", "c"]}), uri, storage_options=opts, mode="overwrite")

    # 2) metadata-service(真 Gravitino)注册 → 查回(Gravitino location 记 s3a://,同 bucket/key)
    g = GravitinoClient(base_url=gravitino_url)
    _ensure_tree(g, minio_s3)
    client = TestClient(build_app(gravitino=g))
    base = "/v1/catalogs/data/schemas/datasets/datasets"
    hdr = {"x-test-claims": json.dumps({"sub": "u-alice", "groups": ["/e-0001/g-0001/members"]})}
    loc = f"s3a://{minio_bucket}/e-0001/g-0001/processed/{n}.lance"

    assert client.post(base, headers=hdr,
                       json={"name": n, "group_id": "g-0001", "location": loc}).status_code == 201
    got = client.get(f"{base}/{n}", headers=hdr).json()
    assert got["group_id"] == "g-0001"
    assert got["location"] == loc

    # 3) 注册的 location 确实指向真 Lance(读回 3 行)
    assert lance.dataset(uri, storage_options=opts).count_rows() == 3
