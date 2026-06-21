import json, httpx, pytest
from fastapi.testclient import TestClient
from libs.audit.oss_audit import AuditWriter
from services.data_pipeline_service.app import build_app
from services.data_pipeline_service.raw_store import RawDatasetStore
from services.data_pipeline_service.upload import Uploader

pytestmark = pytest.mark.integration

class MemSink:
    def __init__(self): self.items = []
    def put(self, key, body): self.items.append((key, body))

def _hdr(sub, groups): return {"x-test-claims": json.dumps({"sub": sub, "groups": groups})}

def test_presigned_single_roundtrip_on_minio(tmp_path, minio_s3, minio_bucket, monkeypatch):
    monkeypatch.setenv("LITEAI_ALLOW_TEST_CLAIMS", "1")
    up = Uploader(raw_store=RawDatasetStore(str(tmp_path)), s3=minio_s3, data_bucket=minio_bucket, url_ttl=900)
    c = TestClient(build_app(runner=None, audit=AuditWriter(MemSink()), uploader=up))

    g = c.post("/v1/data/raw", headers=_hdr("u-a", ["/e-0001/g-0001/members"]),
               json={"dataset": "cc3m", "group_id": "g-0001", "filename": "part-0.bin"}).json()
    assert g["oss_key"] == "e-0001/g-0001/raw/cc3m/part-0.bin"

    body = b"hello-raw" * 1000
    put = httpx.put(g["url"], content=body, timeout=30)           # 纯 PUT 模拟浏览器直传
    assert put.status_code in (200, 201)

    out = c.post(f"/v1/data/raw/{g['raw_id']}/complete",
                 headers=_hdr("u-a", ["/e-0001/g-0001/members"]), json={}).json()
    assert out["status"] == "ready" and out["size"] == len(body)

    lst = c.get("/v1/data/raw", headers=_hdr("u-a", ["/e-0001/g-0001/members"])).json()
    assert lst["total"] == 1 and lst["raw"][0]["status"] == "ready"

def test_presigned_multipart_roundtrip_on_minio(tmp_path, minio_s3, minio_bucket, monkeypatch):
    monkeypatch.setenv("LITEAI_ALLOW_TEST_CLAIMS", "1")
    up = Uploader(raw_store=RawDatasetStore(str(tmp_path)), s3=minio_s3, data_bucket=minio_bucket, url_ttl=900)
    c = TestClient(build_app(runner=None, audit=AuditWriter(MemSink()), uploader=up))

    g = c.post("/v1/data/raw", headers=_hdr("u-a", ["/e-0001/g-0001/members"]),
               json={"dataset": "cc3m", "group_id": "g-0001", "filename": "big.bin",
                     "multipart": True, "parts": 2}).json()
    part = b"x" * (5 * 1024 * 1024)                               # 5 MiB(分片下限)
    etags = []
    for i, url in enumerate(g["part_urls"], start=1):
        r = httpx.put(url, content=part, timeout=120)
        assert r.status_code in (200, 201)
        etags.append({"part_number": i, "etag": r.headers["ETag"]})
    out = c.post(f"/v1/data/raw/{g['raw_id']}/complete",
                 headers=_hdr("u-a", ["/e-0001/g-0001/members"]),
                 json={"parts": etags}).json()
    assert out["status"] == "ready" and out["size"] == len(part) * 2
