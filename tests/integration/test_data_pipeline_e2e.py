import io, tarfile, pytest
import lance
from services.data_pipeline_service.jobs import JobSpec, JobStore
from services.data_pipeline_service import worker as W
pytestmark = pytest.mark.integration

_PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de"
                     "0000000c4944415408d763f8cfc0000003010100c9fe92ef0000000049454e44ae426082")

def _mk_tar(p):
    with tarfile.open(p, "w") as tf:
        for k, t in [("0", "a cat"), ("1", "blue sky")]:
            ti = tarfile.TarInfo(f"{k}.jpg"); ti.size = len(_PNG); tf.addfile(ti, io.BytesIO(_PNG))
            b = t.encode(); ti2 = tarfile.TarInfo(f"{k}.txt"); ti2.size = len(b); tf.addfile(ti2, io.BytesIO(b))

def test_prepare_job_to_lance_on_minio(tmp_path, minio_s3, minio_bucket, monkeypatch, dj_passthrough_bin):
    tar_dir = tmp_path / "tars"; tar_dir.mkdir(); _mk_tar(tar_dir / "s.tar")
    monkeypatch.setenv("DATA_BUCKET", minio_bucket); monkeypatch.setenv("AUDIT_BUCKET", minio_bucket)
    monkeypatch.setenv("OSS_ENDPOINT", "http://localhost:9000")
    monkeypatch.setenv("OSS_ACCESS_KEY", "minio"); monkeypatch.setenv("OSS_SECRET_KEY", "minio123")
    monkeypatch.setenv("OSS_REGION", "us-east-1"); monkeypatch.setenv("DJ_BIN", dj_passthrough_bin)
    store = JobStore(str(tmp_path / "jobs"))
    store.create(JobSpec("job-1", "cc3m", "g-0001", "e-0001", "member", "u-a", str(tar_dir), 2, None))
    store.update("job-1", "running")
    W.run_job(str(store.job_dir("job-1")))
    r = store.read("job-1")
    assert r["status"] == "succeeded" and r["rows_written"] == 2
    ds = lance.dataset(r["lance_uri"], storage_options={
        "access_key_id": "minio", "secret_access_key": "minio123", "endpoint": "http://localhost:9000",
        "region": "us-east-1", "allow_http": "true", "virtual_hosted_style_request": "false"})
    assert ds.count_rows() == 2
