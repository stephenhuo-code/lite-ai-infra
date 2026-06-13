# tests/integration/test_metadata_gravitino.py
import uuid

import pytest

from services.metadata_service.gravitino import GravitinoClient

pytestmark = pytest.mark.integration

# Gravitino 容器经 dev_default 网络以别名 `minio` 访问 MinIO(非宿主 localhost)。
_GRAVITINO_S3_ENDPOINT = "http://minio:9000"
_CATALOG_BUCKET = "lite-ai-dev"


def _ensure_bucket(minio_s3, name):
    if name not in [b["Name"] for b in minio_s3.list_buckets()["Buckets"]]:
        minio_s3.create_bucket(Bucket=name)


def _ensure_tree(g, minio_s3):
    """metalake e_0001 + FILESET catalog(path-style)+ schema datasets(幂等)。
    catalog 的 schema 位置会被 Gravitino 真实校验,故 bucket 须先存在(见 RESULTS.md)。"""
    _ensure_bucket(minio_s3, _CATALOG_BUCKET)
    g.ensure_metalake("e_0001")
    g.ensure_catalog("e_0001", "data", bucket=_CATALOG_BUCKET,
                     s3_endpoint=_GRAVITINO_S3_ENDPOINT, access_key="minio", secret_key="minio123")
    g.ensure_schema("e_0001", "data", "datasets")


def test_real_gravitino_crud(gravitino_url, minio_s3):
    g = GravitinoClient(base_url=gravitino_url)
    _ensure_tree(g, minio_s3)

    # 导航:catalog/schema 可列
    assert "data" in g.list_catalogs("e_0001")
    assert "datasets" in g.list_schemas("e_0001", "data")

    # create → list → get(EXTERNAL fileset,owner 属性原样回写)
    n = f"it_{uuid.uuid4().hex[:6]}"
    loc = f"s3a://{_CATALOG_BUCKET}/e-0001/g-0001/processed/{n}.lance"
    g.create_fileset("e_0001", "data", "datasets", n, location=loc, comment="it",
                     properties={"owner_group": "g-0001", "owner_user": "u-alice", "scope": "private"})
    assert n in g.list_filesets("e_0001", "data", "datasets")
    fs = g.get_fileset("e_0001", "data", "datasets", n)
    assert fs["properties"]["owner_group"] == "g-0001"
    assert fs["storageLocation"] == loc
    assert fs["audit"]["createTime"]  # audit 字段确实回传
