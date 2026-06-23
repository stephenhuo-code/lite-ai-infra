#!/usr/bin/env python3
"""一次性建企业目录骨架:metalake(e_XXXX)+ catalog(data,OSS-fileset)+ schema(datasets)。
provisioner-lite(S2c 并入正式 provisioner)。用法:bootstrap_catalog.py [e-0001]"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 仓库根入 sys.path(同 scripts/load_env.py)

from services.metadata_service.gravitino import GravitinoClient


def _ensure_bucket() -> None:
    """确保 DATA_BUCKET 在(Gravitino 建 schema location 要求桶先存在)。
    用宿主机 OSS_ENDPOINT(localhost:9000)建桶;catalog 配置用容器视角 minio:9000(见下)。"""
    import boto3
    from libs.audit.oss_audit import oss_boto3_config
    ep = os.environ["OSS_ENDPOINT"]
    s3 = boto3.client("s3", endpoint_url=ep, aws_access_key_id=os.environ["OSS_ACCESS_KEY"],
                      aws_secret_access_key=os.environ["OSS_SECRET_KEY"],
                      region_name=os.getenv("OSS_REGION", "us-east-1"), config=oss_boto3_config(ep))
    bucket = os.environ["DATA_BUCKET"]
    try:
        s3.create_bucket(Bucket=bucket)
    except s3.exceptions.BucketAlreadyOwnedByYou:
        pass
    except Exception as e:  # 已存在(BucketAlreadyExists)等幂等容忍
        if "BucketAlreadyExists" not in str(e) and "BucketAlreadyOwnedByYou" not in str(e):
            raise


def main(eid: str) -> int:
    ml = eid.replace("-", "_")
    _ensure_bucket()
    g = GravitinoClient(base_url=os.environ.get("GRAVITINO_URL", "http://localhost:8091"))
    g.ensure_metalake(ml)
    # catalog 的 s3_endpoint 由 Gravitino **容器内**使用 → 必须是 docker 网络地址(minio:9000),
    # 而非宿主机 OSS_ENDPOINT(localhost:9000)。dev 默认 minio:9000;prod 真 OSS 时两者一致。
    g.ensure_catalog(ml, "data", bucket=os.environ["DATA_BUCKET"],
                     s3_endpoint=os.environ.get("GRAVITINO_OSS_ENDPOINT", "http://minio:9000"),
                     access_key=os.environ["OSS_ACCESS_KEY"], secret_key=os.environ["OSS_SECRET_KEY"])
    g.ensure_schema(ml, "data", "datasets")
    print(f"bootstrapped {ml}/data/datasets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "e-0001"))
