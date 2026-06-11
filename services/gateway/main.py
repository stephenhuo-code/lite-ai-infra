# services/gateway/main.py    启动：uvicorn services.gateway.main:app
import os, boto3
from botocore.config import Config
from libs.audit.oss_audit import OssAuditSink, AuditWriter, addressing_style
from services.gateway.app import build_app


def _audit_writer() -> AuditWriter:
    endpoint = os.environ["OSS_ENDPOINT"]               # MinIO http://localhost:9000 / OSS https://oss-...
    s3 = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=os.environ["OSS_ACCESS_KEY"],
        aws_secret_access_key=os.environ["OSS_SECRET_KEY"],
        region_name=os.getenv("OSS_REGION", "us-east-1"),
        config=Config(s3={"addressing_style": addressing_style(
            endpoint, os.getenv("OSS_ADDRESSING_STYLE"))}))
    return AuditWriter(OssAuditSink(bucket=os.environ["AUDIT_BUCKET"], client=s3))


app = build_app(audit=_audit_writer())
