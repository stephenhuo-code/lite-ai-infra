import pytest
from services.data_pipeline_service.raw_store import RawDatasetStore
from services.data_pipeline_service.upload import Uploader

class FakeS3:
    """boto3 S3 子集 fake:记录调用 + 可控对象存在性。"""
    def __init__(self, existing=None):
        self.existing = dict(existing or {})        # key -> size
        self.aborted = []; self.completed = []
    def generate_presigned_url(self, op, Params, ExpiresIn):
        if op == "put_object":
            return f"https://oss.test/{Params['Key']}?sig=single"
        if op == "upload_part":
            return f"https://oss.test/{Params['Key']}?partNumber={Params['PartNumber']}&uploadId={Params['UploadId']}&sig=part"
        raise AssertionError(op)
    def create_multipart_upload(self, Bucket, Key, **kw):
        return {"UploadId": "UP-1"}
    def complete_multipart_upload(self, Bucket, Key, UploadId, MultipartUpload):
        self.completed.append((Key, UploadId)); self.existing[Key] = 999
        return {}
    def abort_multipart_upload(self, Bucket, Key, UploadId):
        self.aborted.append((Key, UploadId))
    def head_object(self, Bucket, Key):
        if Key not in self.existing:
            from botocore.exceptions import ClientError
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        return {"ContentLength": self.existing[Key]}

def _uploader(tmp_path, s3):
    return Uploader(raw_store=RawDatasetStore(str(tmp_path)), s3=s3, data_bucket="lite-ai", url_ttl=900)

def test_create_grant_single_builds_isolated_key_and_url(tmp_path):
    up = _uploader(tmp_path, FakeS3())
    g = up.create_grant(name="cc3m", enterprise_id="e-0001", group_id="g-0001",
                        sub="u-a", filename="part-0.tar", multipart=False, parts=None)
    assert g["oss_key"] == "e-0001/g-0001/raw/cc3m/part-0.tar"
    assert g["url"] and g["upload_id"] is None and g["part_urls"] is None and g["expires_in"] == 900
    rec = up.get_record(g["raw_id"])
    assert rec["status"] == "pending" and rec["enterprise_id"] == "e-0001"   # 记录已建

def test_create_grant_rejects_bad_filename_no_record(tmp_path):
    up = _uploader(tmp_path, FakeS3())
    with pytest.raises(ValueError):
        up.create_grant(name="cc3m", enterprise_id="e-0001", group_id="g-0001",
                        sub="u-a", filename="../escape", multipart=False, parts=None)
    assert up.list_raw() == []     # 零副作用:校验失败不建记录

def test_create_grant_multipart_presigns_each_part(tmp_path):
    up = _uploader(tmp_path, FakeS3())
    g = up.create_grant(name="cc3m", enterprise_id="e-0001", group_id="g-0001",
                        sub="u-a", filename="big.tar", multipart=True, parts=3)
    assert g["upload_id"] == "UP-1" and len(g["part_urls"]) == 3 and g["url"] is None
    assert up.get_record(g["raw_id"])  # pending 记录含 upload_id
    assert up.raw_store.load_spec(g["raw_id"]).upload_id == "UP-1"

def test_finalize_single_marks_ready_with_size(tmp_path):
    s3 = FakeS3()
    up = _uploader(tmp_path, s3)
    g = up.create_grant(name="cc3m", enterprise_id="e-0001", group_id="g-0001",
                        sub="u-a", filename="part-0.tar", multipart=False, parts=None)
    s3.existing[g["oss_key"]] = 4096       # 模拟客户端已直传
    out = up.finalize(g["raw_id"], parts=None)
    assert out["status"] == "ready" and out["size"] == 4096

def test_finalize_object_missing_raises_objectmissing(tmp_path):
    up = _uploader(tmp_path, FakeS3())     # 对象不存在
    g = up.create_grant(name="cc3m", enterprise_id="e-0001", group_id="g-0001",
                        sub="u-a", filename="part-0.tar", multipart=False, parts=None)
    from services.data_pipeline_service.upload import ObjectMissing
    with pytest.raises(ObjectMissing):
        up.finalize(g["raw_id"], parts=None)
    assert up.get_record(g["raw_id"])["status"] == "failed"   # 标 failed

def test_finalize_multipart_completes_then_ready(tmp_path):
    s3 = FakeS3()
    up = _uploader(tmp_path, s3)
    g = up.create_grant(name="cc3m", enterprise_id="e-0001", group_id="g-0001",
                        sub="u-a", filename="big.tar", multipart=True, parts=2)
    out = up.finalize(g["raw_id"], parts=[{"part_number": 1, "etag": "e1"}, {"part_number": 2, "etag": "e2"}])
    assert out["status"] == "ready" and (g["oss_key"], "UP-1") in s3.completed

def test_gc_aborts_multipart_and_deletes_stale_pending(tmp_path):
    s3 = FakeS3()
    up = _uploader(tmp_path, s3)
    g = up.create_grant(name="cc3m", enterprise_id="e-0001", group_id="g-0001",
                        sub="u-a", filename="big.tar", multipart=True, parts=2)
    reaped = up.gc(ttl_seconds=0)           # ttl=0 → 立即视为超时
    assert g["raw_id"] in reaped
    assert (g["oss_key"], "UP-1") in s3.aborted   # 孤儿分片 abort(防漏钱)
    assert up.get_record(g["raw_id"]) is None      # 记录已删
