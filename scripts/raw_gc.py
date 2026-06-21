"""清理超时未完成的 pending 原始上传(ADR-020 §3):abort 孤儿分片 + 删记录。
运维按需 cron:`uv run python scripts/raw_gc.py`。周期/TTL 由 env 控,非本地阻塞。"""
import os, sys
import boto3
from libs.audit.oss_audit import oss_boto3_config
from services.data_pipeline_service.raw_store import RawDatasetStore
from services.data_pipeline_service.upload import Uploader

def main() -> int:
    endpoint = os.environ["OSS_ENDPOINT"]
    s3 = boto3.client("s3", endpoint_url=endpoint, aws_access_key_id=os.environ["OSS_ACCESS_KEY"],
                      aws_secret_access_key=os.environ["OSS_SECRET_KEY"],
                      aws_session_token=os.getenv("OSS_SESSION_TOKEN"),
                      region_name=os.getenv("OSS_REGION", "cn-hangzhou"), config=oss_boto3_config(endpoint))
    up = Uploader(raw_store=RawDatasetStore(os.environ.get("RAW_DIR", "./.raw")),
                  s3=s3, data_bucket=os.environ["DATA_BUCKET"])
    ttl = int(os.getenv("RAW_PENDING_TTL", "3600"))
    reaped = up.gc(ttl_seconds=ttl)
    print(f"raw_gc: reaped {len(reaped)} stale pending: {reaped}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
