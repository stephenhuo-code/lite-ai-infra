#!/usr/bin/env python3
"""一次性建企业目录骨架:metalake(e_XXXX)+ catalog(data,OSS-fileset)+ schema(datasets)。
provisioner-lite(S2c 并入正式 provisioner)。用法:bootstrap_catalog.py [e-0001]"""
import os
import sys

from services.metadata_service.gravitino import GravitinoClient


def main(eid: str) -> int:
    ml = eid.replace("-", "_")
    g = GravitinoClient(base_url=os.environ.get("GRAVITINO_URL", "http://localhost:8091"))
    g.ensure_metalake(ml)
    g.ensure_catalog(ml, "data", bucket=os.environ["DATA_BUCKET"],
                     s3_endpoint=os.environ["OSS_ENDPOINT"],
                     access_key=os.environ["OSS_ACCESS_KEY"], secret_key=os.environ["OSS_SECRET_KEY"])
    g.ensure_schema(ml, "data", "datasets")
    print(f"bootstrapped {ml}/data/datasets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "e-0001"))
