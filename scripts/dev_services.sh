#!/usr/bin/env bash
# 本地多进程服务的一键起停(后台 + PID 跟踪)。
# 真微服务:每服务独立 uvicorn 进程;deps(Keycloak/MinIO)由 docker compose 管,见 Makefile up/down。
# 日常开发改单个服务时用 `make run-<svc>`(前台 + --reload);本脚本用于"全起/全停"。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PIDDIR="$ROOT/.dev"
mkdir -p "$PIDDIR"
JWKS="${JWKS:-http://localhost:8080/realms/lite-ai/protocol/openid-connect/certs}"

start_one() {
  local name="$1" port="$2"; shift 2
  if [ -f "$PIDDIR/$name.pid" ] && kill -0 "$(cat "$PIDDIR/$name.pid")" 2>/dev/null; then
    echo "  $name 已在跑 (pid $(cat "$PIDDIR/$name.pid"))"; return
  fi
  ( cd "$ROOT" && "$@" ) >"$PIDDIR/$name.log" 2>&1 &
  echo $! > "$PIDDIR/$name.pid"
  echo "  $name → :$port  (pid $!, 日志 .dev/$name.log)"
}

case "${1:-}" in
  up)
    start_one identity 8001 env LITEAI_JWKS_URL="$JWKS" \
      uv run uvicorn services.identity_org_service.main:app --port 8001
    start_one gateway 8090 env IDENTITY_ORG_URL=http://localhost:8001 \
      uv run uvicorn services.gateway.main:app --port 8090
    # Plan 4/5 追加:metadata 8002 / data-pipeline 8003
    echo "  入口:gateway http://localhost:8090  (/docs, /v1/me/orgs)"
    ;;
  down)
    shopt -s nullglob
    for f in "$PIDDIR"/*.pid; do
      pid=$(cat "$f"); name=$(basename "$f" .pid)
      kill "$pid" 2>/dev/null && echo "  停 $name (pid $pid)" || echo "  $name 已停"
      rm -f "$f"
    done
    ;;
  ps)
    shopt -s nullglob
    for f in "$PIDDIR"/*.pid; do
      pid=$(cat "$f"); name=$(basename "$f" .pid)
      kill -0 "$pid" 2>/dev/null && echo "  $name: 运行中 (pid $pid)" || echo "  $name: 已死(残留 pid 文件)"
    done
    ;;
  *) echo "usage: dev_services.sh up|down|ps"; exit 1;;
esac
