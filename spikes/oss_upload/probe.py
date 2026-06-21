"""OSS 上传机制探查(Plan 7 / #11 数据集上传,宪法 §3.4 探查优先)。

对真 dev MinIO(deploy/dev/docker-compose.yml,:9000,minio/minio123,path-style)实测:
  §1 presigned 单对象 PUT —— 浏览器直传可行性(用纯 HTTP PUT 模拟浏览器,不带 AWS 凭据)
  §2 presigned 分片 multipart —— 大文件直传(initiate→presign part→PUT part→complete)
  §3 CORS —— 浏览器跨源直传 MinIO 是否需配置 / 默认行为(OPTIONS 预检)
  §4 代理流式基线 —— gateway 全量 body 进内存(已由 proxy.py 代码确认,这里量化阈值事实)
  §5 S3/MinIO 上传上限事实(单 PUT 上限、分片建议阈值)

复现:dev MinIO 起来后 `uv run python spikes/oss_upload/probe.py`
实现以本探查结论(probe.md)为准,禁止把猜测写进 ADR/契约/tasks。
"""
from __future__ import annotations

import io
import os
import sys

import boto3
import httpx
from botocore.config import Config

ENDPOINT = os.environ.get("OSS_ENDPOINT", "http://localhost:9000")
ACCESS = os.environ.get("OSS_ACCESS_KEY", "minio")
SECRET = os.environ.get("OSS_SECRET_KEY", "minio123")
REGION = os.environ.get("OSS_REGION", "us-east-1")
BUCKET = os.environ.get("DATA_BUCKET", "lite-ai")

# path-style for MinIO(对齐 libs/audit/oss_audit.py:oss_boto3_config 的 dev 行为)
_cfg = Config(signature_version="s3v4", s3={"addressing_style": "path"})


def _client():
    return boto3.client(
        "s3",
        endpoint_url=ENDPOINT,
        aws_access_key_id=ACCESS,
        aws_secret_access_key=SECRET,
        region_name=REGION,
        config=_cfg,
    )


def _ensure_bucket(s3):
    try:
        s3.head_bucket(Bucket=BUCKET)
    except Exception:
        s3.create_bucket(Bucket=BUCKET)


PASS, FAIL = "PASS", "FAIL"
results: list[tuple[str, str, str]] = []


def record(name, status, detail):
    results.append((name, status, detail))
    print(f"[{status}] {name}: {detail}")


def probe_presigned_put(s3):
    """§1 presigned 单对象 PUT —— 模拟浏览器拿 URL 直传(请求不带 AWS 凭据)。"""
    key = "e-0001/g-0001/raw/probe/single.bin"
    body = b"x" * (5 * 1024 * 1024)  # 5 MiB
    url = s3.generate_presigned_url(
        "put_object",
        Params={"Bucket": BUCKET, "Key": key, "ContentType": "application/octet-stream"},
        ExpiresIn=900,
    )
    # 纯 HTTP PUT,不带任何 AWS 凭据/SDK —— 这正是浏览器/fetch 的行为
    r = httpx.put(url, content=body, headers={"Content-Type": "application/octet-stream"}, timeout=60)
    if r.status_code not in (200, 201):
        record("presigned-single-PUT", FAIL, f"PUT {r.status_code} {r.text[:200]}")
        return
    head = s3.head_object(Bucket=BUCKET, Key=key)
    ok = head["ContentLength"] == len(body)
    record(
        "presigned-single-PUT",
        PASS if ok else FAIL,
        f"5MiB 直传(无 AWS 凭据)落 {key},size={head['ContentLength']} url_len={len(url)}",
    )


def probe_presigned_multipart(s3):
    """§2 presigned 分片 —— 大文件直传:每个 part 单独 presign,浏览器并行 PUT。"""
    key = "e-0001/g-0001/raw/probe/multi.bin"
    part_size = 5 * 1024 * 1024  # MinIO/S3 分片最小 5 MiB(末片除外)
    n_parts = 3
    try:
        mp = s3.create_multipart_upload(Bucket=BUCKET, Key=key, ContentType="application/octet-stream")
        upload_id = mp["UploadId"]
    except Exception as e:  # noqa: BLE001
        record("presigned-multipart", FAIL, f"create_multipart_upload err: {e}")
        return
    parts = []
    try:
        for i in range(1, n_parts + 1):
            url = s3.generate_presigned_url(
                "upload_part",
                Params={"Bucket": BUCKET, "Key": key, "UploadId": upload_id, "PartNumber": i},
                ExpiresIn=900,
            )
            chunk = (b"%d" % i) * part_size  # >=5MiB 内容
            chunk = chunk[:part_size]
            r = httpx.put(url, content=chunk, timeout=120)  # 浏览器视角:纯 PUT
            if r.status_code not in (200, 201):
                record("presigned-multipart", FAIL, f"part{i} PUT {r.status_code} {r.text[:160]}")
                s3.abort_multipart_upload(Bucket=BUCKET, Key=key, UploadId=upload_id)
                return
            parts.append({"ETag": r.headers["ETag"], "PartNumber": i})
        s3.complete_multipart_upload(
            Bucket=BUCKET, Key=key, UploadId=upload_id, MultipartUpload={"Parts": parts}
        )
    except Exception as e:  # noqa: BLE001
        record("presigned-multipart", FAIL, f"part/complete err: {e}")
        try:
            s3.abort_multipart_upload(Bucket=BUCKET, Key=key, UploadId=upload_id)
        except Exception:
            pass
        return
    head = s3.head_object(Bucket=BUCKET, Key=key)
    expect = part_size * n_parts
    record(
        "presigned-multipart",
        PASS if head["ContentLength"] == expect else FAIL,
        f"{n_parts}×5MiB 分片直传(每片单独 presign,纯 PUT)落 {key},size={head['ContentLength']}",
    )


def probe_cors(s3):
    """§3 CORS —— 浏览器跨源直传是否需配置。试 put_bucket_cors + OPTIONS 预检。"""
    detail_parts = []
    # 3a: MinIO 是否接受 put_bucket_cors(S3 CORS API)
    try:
        s3.put_bucket_cors(
            Bucket=BUCKET,
            CORSConfiguration={
                "CORSRules": [
                    {
                        "AllowedHeaders": ["*"],
                        "AllowedMethods": ["PUT", "GET", "POST"],
                        "AllowedOrigins": ["http://localhost:5173"],
                        "ExposeHeaders": ["ETag"],
                        "MaxAgeSeconds": 3000,
                    }
                ]
            },
        )
        detail_parts.append("put_bucket_cors=OK(S3 CORS API 受理)")
    except Exception as e:  # noqa: BLE001
        detail_parts.append(f"put_bucket_cors=ERR({type(e).__name__})")
    # 3b: OPTIONS 预检带 Origin,看回 Access-Control-Allow-Origin
    key = "e-0001/g-0001/raw/probe/single.bin"
    url = s3.generate_presigned_url(
        "put_object", Params={"Bucket": BUCKET, "Key": key}, ExpiresIn=300
    )
    base = url.split("?")[0]
    try:
        r = httpx.options(
            base,
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "PUT",
                "Access-Control-Request-Headers": "content-type",
            },
            timeout=15,
        )
        acao = r.headers.get("access-control-allow-origin")
        detail_parts.append(f"OPTIONS={r.status_code} ACAO={acao!r}")
        status = PASS if acao else FAIL
    except Exception as e:  # noqa: BLE001
        detail_parts.append(f"OPTIONS err: {e}")
        status = FAIL
    record("cors-browser-direct", status, " | ".join(detail_parts))


def probe_sts(s3):
    """§4 STS AssumeRole —— 短期受限凭据可行性(可选,直传更安全的方案)。"""
    try:
        sts = boto3.client(
            "sts",
            endpoint_url=ENDPOINT,
            aws_access_key_id=ACCESS,
            aws_secret_access_key=SECRET,
            region_name=REGION,
            config=_cfg,
        )
        # MinIO 支持 AssumeRole(需 root 或带 policy);仅探可达性
        resp = sts.assume_role(
            RoleArn="arn:minio:iam:::role/dummy",
            RoleSessionName="probe",
            DurationSeconds=900,
        )
        has = "Credentials" in resp
        record("sts-assume-role", PASS if has else FAIL, f"AssumeRole 可达,Credentials={has}")
    except Exception as e:  # noqa: BLE001
        # 失败不代表不可用,多半是缺 policy/role 配置;记事实供 ADR 研判
        record("sts-assume-role", "INFO", f"AssumeRole 未通(多为缺 role/policy 配置):{type(e).__name__}: {str(e)[:160]}")


def main():
    print(f"== OSS 上传探查 == endpoint={ENDPOINT} bucket={BUCKET} addressing=path-style\n")
    s3 = _client()
    try:
        _ensure_bucket(s3)
    except Exception as e:  # noqa: BLE001
        print(f"FATAL: 无法连 MinIO / 建桶:{e}", file=sys.stderr)
        sys.exit(2)
    probe_presigned_put(s3)
    probe_presigned_multipart(s3)
    probe_cors(s3)
    probe_sts(s3)
    print("\n== 汇总 ==")
    for name, status, detail in results:
        print(f"  {status:5} {name}")
    hard_fail = [r for r in results if r[1] == FAIL]
    sys.exit(1 if hard_fail else 0)


if __name__ == "__main__":
    main()
