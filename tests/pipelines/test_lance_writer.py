# tests/pipelines/test_lance_writer.py
from pipelines.data_prep.lance_writer import lance_storage_options, needs_commit_lock

def test_storage_options_minio_path_style():
    o = lance_storage_options("http://localhost:9000", "bkt", "ak", "sk")
    assert o["endpoint"] == "http://localhost:9000"
    assert o["virtual_hosted_style_request"] == "false"
    assert o["allow_http"] == "true"
    assert "conditional_put" not in o          # MinIO 走默认条件写

def test_storage_options_oss_virtual_bucket_in_endpoint():
    o = lance_storage_options("https://oss-cn-hangzhou-internal.aliyuncs.com", "bkt", "ak", "sk",
                              session_token="tok")
    assert o["endpoint"] == "https://bkt.oss-cn-hangzhou-internal.aliyuncs.com"  # 约束3
    assert o["virtual_hosted_style_request"] == "true"                            # 约束1
    assert o["session_token"] == "tok"

def test_oss_needs_commit_lock():
    assert needs_commit_lock("https://oss-cn-hangzhou.aliyuncs.com") is True      # If-None-Match 缺失
    assert needs_commit_lock("http://localhost:9000") is False
