# services/data_pipeline_service/main.py  启动:uvicorn services.data_pipeline_service.main:app --port 8003
import os
import boto3
from libs.audit.oss_audit import OssAuditSink, AuditWriter, oss_boto3_config
from services.data_pipeline_service.app import build_app
from services.data_pipeline_service.jobs import JobStore
from services.data_pipeline_service.scheduler import SubprocessJobRunner
from services.data_pipeline_service.raw_store import RawDatasetStore
from services.data_pipeline_service.upload import Uploader

_endpoint = os.environ["OSS_ENDPOINT"]
_s3 = boto3.client("s3", endpoint_url=_endpoint, aws_access_key_id=os.environ["OSS_ACCESS_KEY"],
                   aws_secret_access_key=os.environ["OSS_SECRET_KEY"],
                   aws_session_token=os.getenv("OSS_SESSION_TOKEN"),
                   region_name=os.getenv("OSS_REGION", "cn-hangzhou"), config=oss_boto3_config(_endpoint))
# runner 自管后台调度线程(队列推进 + PID 看门狗);main.py 对 runner 实现无感 →
# S2a 唯一改动 = 下一行换 ArgoJobRunner(build_app 不变)。
_runner = SubprocessJobRunner(JobStore(os.environ.get("JOBS_DIR", "./.jobs")), dispatch_interval=2.0)
_uploader = Uploader(raw_store=RawDatasetStore(os.environ.get("RAW_DIR", "./.raw")),
                     s3=_s3, data_bucket=os.environ["DATA_BUCKET"],
                     url_ttl=int(os.getenv("UPLOAD_URL_TTL", "900")))
app = build_app(runner=_runner, audit=AuditWriter(OssAuditSink(bucket=os.environ["AUDIT_BUCKET"], client=_s3)),
                uploader=_uploader)
