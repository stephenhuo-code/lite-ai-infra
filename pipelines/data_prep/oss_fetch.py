from __future__ import annotations
import os
from pathlib import Path
import boto3
from libs.audit.oss_audit import oss_boto3_config

def build_s3(endpoint, access_key, secret_key, session_token=None, region="cn-hangzhou"):
    return boto3.client("s3", endpoint_url=endpoint, aws_access_key_id=access_key,
                        aws_secret_access_key=secret_key, aws_session_token=session_token,
                        region_name=region, config=oss_boto3_config(endpoint))

def fetch_oss_tars(s3, *, bucket: str, prefix: str, dest_dir: str) -> int:
    """下载 bucket/prefix 下所有 *.tar 到 dest_dir(扁平,用对象名末段)。返回个数。"""
    dest = Path(dest_dir); dest.mkdir(parents=True, exist_ok=True); n = 0
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if not key.endswith(".tar"):
                continue
            s3.download_file(bucket, key, str(dest / os.path.basename(key))); n += 1
    return n
