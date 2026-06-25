# pipelines/data_prep/__main__.py
"""一行命令:python -m pipelines.data_prep --tar-dir … --dataset cc3m

凭据/endpoint 走 env(OSS_* / DATA_BUCKET / AUDIT_BUCKET);调用者身份 v1 CLI 态走
LITEAI_SUB/LITEAI_GROUPS env(服务化入口在 data-pipeline-service,Plan 4)。
DJ_BIN 指向外部 venv 的 dj-process(spike 教训:Ray 禁瞬态环境);需 Ray head 已起。"""
from __future__ import annotations

import argparse
import json
import os
import sys

import boto3

from libs.identity.context import parse_context
from libs.audit.oss_audit import OssAuditSink, AuditWriter, oss_boto3_config
from pipelines.data_prep.runner import PrepareRequest, run_prepare


def main() -> int:
    ap = argparse.ArgumentParser("data-prep")
    ap.add_argument("--tar-dir", required=True)
    ap.add_argument("--work-dir", default="./.dataprep")
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--enterprise", default="ent-demo")
    ap.add_argument("--np", type=int, default=int(os.getenv("DJ_NP", (os.cpu_count() or 2) + 1)))
    a = ap.parse_args()

    # 身份降两级(ADR-025):CLI 态调用者身份走 LITEAI_SUB + LITEAI_ORGANIZATION(org alias 数组)
    # / LITEAI_REALM_ROLES;默认归属 --enterprise(单企业 member,无用户组层)。
    ctx = parse_context(sub=os.getenv("LITEAI_SUB", "cli-user"),
                        organization=json.loads(os.getenv("LITEAI_ORGANIZATION", f'["{a.enterprise}"]')),
                        realm_roles=json.loads(os.getenv("LITEAI_REALM_ROLES", "[]")))
    endpoint = os.environ["OSS_ENDPOINT"]
    s3 = boto3.client("s3", endpoint_url=endpoint,
                      aws_access_key_id=os.environ["OSS_ACCESS_KEY"],
                      aws_secret_access_key=os.environ["OSS_SECRET_KEY"],
                      aws_session_token=os.getenv("OSS_SESSION_TOKEN"),
                      region_name=os.getenv("OSS_REGION", "cn-hangzhou"),
                      config=oss_boto3_config(endpoint))
    audit = AuditWriter(OssAuditSink(bucket=os.environ["AUDIT_BUCKET"], client=s3))
    req = PrepareRequest(tar_dir=a.tar_dir, work_dir=a.work_dir, bucket=os.environ["DATA_BUCKET"],
                         enterprise_id=a.enterprise, dataset=a.dataset,
                         np=a.np, oss_endpoint=endpoint,
                         access_key=os.environ["OSS_ACCESS_KEY"],
                         secret_key=os.environ["OSS_SECRET_KEY"],
                         session_token=os.getenv("OSS_SESSION_TOKEN"),
                         region=os.getenv("OSS_REGION", "cn-hangzhou"))
    out = run_prepare(ctx, req, audit)
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
