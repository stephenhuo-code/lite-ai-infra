"""detached 作业 worker:python -m services.data_pipeline_service.worker --job-dir <dir>
读 spec → 重建 Context(快照角色)→ run_prepare(内部 can() 复检 + 审计)→ 写终态。"""
from __future__ import annotations
import argparse, os, sys
import boto3
from libs.identity.context import Context, Membership
from libs.identity.ids import EnterpriseId
from libs.audit.oss_audit import OssAuditSink, AuditWriter, oss_boto3_config
from pipelines.data_prep.runner import PrepareRequest, run_prepare
from services.data_pipeline_service.jobs import JobStore

def _audit_writer() -> AuditWriter:
    endpoint = os.environ["OSS_ENDPOINT"]
    s3 = boto3.client("s3", endpoint_url=endpoint,
                      aws_access_key_id=os.environ["OSS_ACCESS_KEY"],
                      aws_secret_access_key=os.environ["OSS_SECRET_KEY"],
                      aws_session_token=os.getenv("OSS_SESSION_TOKEN"),
                      region_name=os.getenv("OSS_REGION", "cn-hangzhou"),
                      config=oss_boto3_config(endpoint))
    return AuditWriter(OssAuditSink(bucket=os.environ["AUDIT_BUCKET"], client=s3))

def run_job(job_dir: str) -> None:
    root, job_id = os.path.dirname(job_dir.rstrip("/")), os.path.basename(job_dir.rstrip("/"))
    store = JobStore(root)
    spec = store.load_spec(job_id)
    if spec is None:        # spec.json 缺失/损坏:写终态而非崩成无终态的孤儿 running
        store.update(job_id, "failed", error="spec.json missing or unreadable")
        return
    # owner 模型(ADR-024):重建 Context 用 sub(=owner)+ 企业级 membership(无组);
    # can() 复检按企业隔离 + owner==user(runner 把 resource.owner 钉成 ctx.user)。
    ctx = Context(user=spec.sub, memberships=[
        Membership(EnterpriseId(spec.enterprise_id), spec.role)])
    req = PrepareRequest(
        tar_dir="", source_location=spec.source_location,    # catalog-driven:从 OSS location 取 tar(tar_dir 旧本地路径已废)
        work_dir=str(store.job_dir(job_id) / "work"),
        bucket=os.environ["DATA_BUCKET"], enterprise_id=spec.enterprise_id,
        dataset=spec.dataset, np=spec.np,
        oss_endpoint=os.environ["OSS_ENDPOINT"], access_key=os.environ["OSS_ACCESS_KEY"],
        secret_key=os.environ["OSS_SECRET_KEY"], session_token=os.getenv("OSS_SESSION_TOKEN"),
        region=os.getenv("OSS_REGION", "cn-hangzhou"), process=spec.process)
    try:
        out = run_prepare(ctx, req, _audit_writer())
        store.update(job_id, "succeeded", rows_in=out["rows_in"],
                     rows_written=out["rows_written"], lance_uri=out["lance_uri"])
    except PermissionError as e:
        store.update(job_id, "failed", error=f"forbidden: {e}")
    except Exception as e:
        store.update(job_id, "failed", error=str(e))

def main() -> int:
    ap = argparse.ArgumentParser("data-pipeline-worker")
    ap.add_argument("--job-dir", required=True)
    run_job(ap.parse_args().job_dir)
    return 0

if __name__ == "__main__":
    sys.exit(main())
