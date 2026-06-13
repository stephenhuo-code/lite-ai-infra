#!/usr/bin/env bash
# Gravitino 探针:实测 metalake→FILESET catalog→schema→fileset 全链 + list/get。
# 输出给 RESULTS.md:确认端点、响应包络键名、fileset 对象字段、s3 path-style 依赖。
# 幂等:先 drop metalake + 建桶,再走全链(可反复跑)。
set -uo pipefail
G=${GRAVITINO_URL:-http://localhost:8091}; ML=e_0001; B=$G/api/metalakes/$ML/catalogs/data/schemas/datasets/filesets
say(){ echo; echo "### $*"; }

say "reset metalake (idempotent)"; curl -sS -X DELETE "$G/api/metalakes/$ML?force=true" -w ' [HTTP %{http_code}]\n'

say "ensure bucket lite-ai-dev (FILESET catalog 在 create schema 时校验 S3 位置存在)"
uv run python - <<'PY' 2>&1 | tail -1 || true
import boto3; from botocore.config import Config
s3=boto3.client("s3",endpoint_url="http://localhost:9000",aws_access_key_id="minio",aws_secret_access_key="minio123",region_name="us-east-1",config=Config(s3={"addressing_style":"path"}))
if "lite-ai-dev" not in [b["Name"] for b in s3.list_buckets()["Buckets"]]: s3.create_bucket(Bucket="lite-ai-dev")
print("bucket ready: lite-ai-dev")
PY

say "metalake create"; curl -sS -X POST "$G/api/metalakes" -H 'Content-Type: application/json' -d '{"name":"'$ML'","comment":"e-0001"}' -w ' [HTTP %{http_code}]\n'

say "catalog create (FILESET → MinIO, path-style 必须)"; curl -sS -X POST "$G/api/metalakes/$ML/catalogs" -H 'Content-Type: application/json' -d '{
  "name":"data","type":"FILESET","comment":"datasets",
  "properties":{"location":"s3a://lite-ai-dev/","filesystem-providers":"s3",
    "s3-endpoint":"http://minio:9000","s3-access-key-id":"minio","s3-secret-access-key":"minio123",
    "s3-path-style-access":"true","gravitino.bypass.fs.s3a.path.style.access":"true"}}' -w ' [HTTP %{http_code}]\n'

say "schema create (会对 s3a://lite-ai-dev/datasets 做真实 getFileStatus 校验)"; curl -sS -X POST "$G/api/metalakes/$ML/catalogs/data/schemas" -H 'Content-Type: application/json' -d '{"name":"datasets","comment":"domain"}' -w ' [HTTP %{http_code}]\n'

say "fileset create (EXTERNAL + owner props)"; curl -sS -X POST "$B" -H 'Content-Type: application/json' -d '{
  "name":"cc3m","type":"EXTERNAL","comment":"probe","storageLocation":"s3a://lite-ai-dev/e-0001/g-0001/processed/cc3m.lance",
  "properties":{"owner_group":"g-0001","owner_user":"u-alice","scope":"private"}}' -w ' [HTTP %{http_code}]\n'

say "list catalogs"; curl -sS "$G/api/metalakes/$ML/catalogs" -w ' [HTTP %{http_code}]\n'
say "list schemas"; curl -sS "$G/api/metalakes/$ML/catalogs/data/schemas" -w ' [HTTP %{http_code}]\n'
say "list filesets"; curl -sS "$B" -w ' [HTTP %{http_code}]\n'
say "get fileset (看 fields: comment/audit/storageLocation/properties)"; curl -sS "$B/cc3m" -w ' [HTTP %{http_code}]\n'
say "get fileset MISSING → 404"; curl -sS "$B/nope" -o /dev/null -w '[HTTP %{http_code}]\n'
