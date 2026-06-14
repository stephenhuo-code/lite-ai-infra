#!/usr/bin/env bash
# 本地多进程服务的一键起停。真微服务:每服务独立 uvicorn 进程;
# deps(Keycloak/MinIO)由 docker compose 管(见 Makefile up/down)。
# 日常改单个服务用 `make run-<svc>`(前台 + --reload);本脚本用于"全起/全停"。
#
# 服务登记表:name|port|uvicorn-target  (新增服务在此加一行,make up/down/ps 自动覆盖)
SERVICES=(
  "identity|8001|services.identity_org_service.main:app"
  "metadata|8002|services.metadata_service.main:app"
  "data-pipeline|8003|services.data_pipeline_service.main:app"
  "gateway|8090|services.gateway.main:app"
)
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PIDDIR="$ROOT/.dev"; mkdir -p "$PIDDIR"
JWKS="${JWKS:-http://localhost:8080/realms/lite-ai/protocol/openid-connect/certs}"

_env_for() {  # 各服务启动 env
  case "$1" in
    identity) echo "LITEAI_JWKS_URL=$JWKS" ;;
    metadata) echo "LITEAI_JWKS_URL=$JWKS GRAVITINO_URL=http://localhost:8091" ;;
    # data-pipeline:JOBS_DIR 状态文件根 + 本地 MinIO 凭据/桶(worker 传给 run_prepare)+ 验签 +
    # DJ_BIN 默认指向 .dj-venv 的真 Data-Juicer(dev/prod parity;先 `make dj-setup` 建好)。
    data-pipeline) echo "LITEAI_JWKS_URL=$JWKS JOBS_DIR=$ROOT/.dev/jobs OSS_ENDPOINT=http://localhost:9000 OSS_ACCESS_KEY=minio OSS_SECRET_KEY=minio123 OSS_REGION=us-east-1 DATA_BUCKET=lite-ai AUDIT_BUCKET=lite-ai DJ_BIN=$ROOT/.dj-venv/bin/dj-process" ;;
    gateway)  echo "IDENTITY_ORG_URL=http://localhost:8001 METADATA_URL=http://localhost:8002 DATA_PIPELINE_URL=http://localhost:8003" ;;
    *)        echo "" ;;
  esac
}

_kill_target() {  # 按 uvicorn target 精确杀(连 uv run 子进程一起);再按端口兜底
  local target="$1" port="$2"
  pkill -f "uvicorn $target" 2>/dev/null
  lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | xargs -r kill 2>/dev/null
}

case "${1:-}" in
  up)
    for row in "${SERVICES[@]}"; do
      IFS='|' read -r name port target <<<"$row"
      if lsof -nP -iTCP:"$port" -sTCP:LISTEN -t >/dev/null 2>&1; then
        echo "  $name 已在 :$port(跳过)"; continue
      fi
      ( cd "$ROOT" && env $(_env_for "$name") uv run uvicorn "$target" --port "$port" ) \
        >"$PIDDIR/$name.log" 2>&1 &
      echo $! > "$PIDDIR/$name.pid"
      echo "  $name → :$port  (日志 .dev/$name.log)"
    done
    echo "  入口:gateway http://localhost:8090  (/docs, /v1/me/orgs)"
    ;;
  down)
    for row in "${SERVICES[@]}"; do
      IFS='|' read -r name port target <<<"$row"
      _kill_target "$target" "$port"
      rm -f "$PIDDIR/$name.pid"
      echo "  停 $name(:$port)"
    done
    ;;
  ps)
    for row in "${SERVICES[@]}"; do
      IFS='|' read -r name port target <<<"$row"
      if lsof -nP -iTCP:"$port" -sTCP:LISTEN -t >/dev/null 2>&1; then
        echo "  $name: 运行中(:$port)"
      else
        echo "  $name: 未运行"
      fi
    done
    ;;
  *) echo "usage: dev_services.sh up|down|ps"; exit 1;;
esac
