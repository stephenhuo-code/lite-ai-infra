# tests/integration/test_lance_minio.py
import json, pytest
import lance
from pipelines.data_prep.lance_writer import lance_storage_options, write_cleaned_to_lance
pytestmark = pytest.mark.integration

def test_write_and_read_lance_on_minio(minio_s3, minio_bucket, tmp_path):
    d = tmp_path / "cleaned"; d.mkdir()
    (d / "part-0.jsonl").write_text("\n".join(
        json.dumps({"text": f"t{i}", "images": [f"/img/{i}.jpg"]}) for i in range(10)))
    ep = "http://localhost:9000"
    opts = lance_storage_options(ep, minio_bucket, "minio", "minio123", region="us-east-1")
    uri = f"s3://{minio_bucket}/e-0001/g-0001/processed/it.lance"
    assert write_cleaned_to_lance(str(d), uri, opts, ep) == 10
    ds = lance.dataset(uri, storage_options=opts)
    assert ds.count_rows() == 10
    assert ds.to_table(columns=["text"]).num_rows == 10
