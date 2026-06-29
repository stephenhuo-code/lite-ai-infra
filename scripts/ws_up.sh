#!/usr/bin/env bash
# Plan 9a Workspace 一键编排:按依赖顺序起全栈 + 等就绪。
#
# 顺序(后者依赖前者就绪):
#   1) deps-dev        —— Keycloak + MinIO 等(docker compose),等 KC 就绪
#   2) provision-orgs  —— 把 alice/bob 以 UNMANAGED 加入企业 org(realm 导入后置备,见 provision_orgs.py)
#   3) omnigent-up     —— 自编译 server+host:dev 镜像 + 起 omnigent server/postgres,等 /health
#   4) services up     —— 主机直跑的 uvicorn(含 gateway:8090,带 OMNIGENT_BASE_URL=127.0.0.1:8900),等 /healthz
#   5) 前端            —— 不后台化;打印 `cd frontend && npm run dev`(owner 自己起 vite:5173)
#
# omnigent 订阅 token:compose 引用 ${CLAUDE_CODE_OAUTH_TOKEN:?};本脚本从 secrets/omnigent.token 读出导出。
# 该 token 是 owner 的 claude 订阅 OAuth token(`secrets/omnigent.token`,不入仓);缺则在第 3 步明确报错。
#
# 幂等:各步都先查在不在(KC/omnigent/gateway 已起则跳过),可重复跑、可在已起的栈上补齐。
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MAKE="${MAKE:-make}"

_wait() {  # _wait <名> <url> <期望子串|""> <超时秒>
  local name="$1" url="$2" want="$3" timeout="${4:-90}" i=0 body
  printf '  等 %s 就绪(%s)' "$name" "$url"
  while (( i < timeout )); do
    body="$(curl -fsS "$url" 2>/dev/null)" && {
      if [[ -z "$want" || "$body" == *"$want"* ]]; then echo "  ✓"; return 0; fi
    }
    printf '.'; sleep 2; i=$((i+2))
  done
  echo "  ✗ 超时(${timeout}s)"; return 1
}

echo "==> [1/5] deps-dev(Keycloak + MinIO 等)"
$MAKE deps-dev || exit 1
_wait "Keycloak" "http://localhost:8080/realms/lite-ai" '"realm"' 120 || {
  echo "ERROR: Keycloak 未就绪;看 docker compose -f deploy/dev/docker-compose.yml logs keycloak" >&2; exit 1; }

echo "==> [2/5] provision-orgs(alice/bob 入企业 org + organization scope)"
uv run python "$ROOT/scripts/provision_orgs.py" || {
  echo "ERROR: 组织置备失败(KC admin 可达?)" >&2; exit 1; }

echo "==> [3/5] omnigent-up(自编译 server+host:dev → 起 omnigent server/postgres)"
TOKEN_FILE="$ROOT/secrets/omnigent.token"
if [[ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]]; then
  if [[ -f "$TOKEN_FILE" ]]; then
    export CLAUDE_CODE_OAUTH_TOKEN="$(tr -d '[:space:]' < "$TOKEN_FILE")"
    echo "  (已从 secrets/omnigent.token 导出 CLAUDE_CODE_OAUTH_TOKEN)"
  else
    echo "ERROR: 缺订阅 token —— 既无 \$CLAUDE_CODE_OAUTH_TOKEN,也无 $TOKEN_FILE" >&2
    echo "       该 token = owner 的 claude 订阅 OAuth token,放 secrets/omnigent.token(不入仓)" >&2
    exit 1
  fi
fi
$MAKE omnigent-up || exit 1
_wait "omnigent" "http://127.0.0.1:8900/health" '"ok"' 120 || {
  echo "ERROR: omnigent 未就绪;看 docker compose -f deploy/dev/omnigent/docker-compose.yml logs omnigent" >&2; exit 1; }

echo "==> [4/5] services up(uvicorn:含 gateway:8090,反代走 OMNIGENT_BASE_URL)"
bash "$ROOT/scripts/dev_services.sh" up || exit 1
_wait "gateway" "http://localhost:8090/healthz" "" 60 || {
  echo "ERROR: gateway 未就绪;看 .dev/gateway.log" >&2; exit 1; }

echo "==> [5/5] 前端(不后台化)"
echo "  起 vite 开发服务器(浏览器入口 http://localhost:5173,代理 /auth /v1 → gateway:8090):"
echo "      cd frontend && npm run dev"
echo
echo "==> ws-up 完成。栈就绪:"
echo "    Keycloak  http://localhost:8080   (用户:alice/alice、bob/bob)"
echo "    omnigent  http://127.0.0.1:8900/health"
echo "    gateway   http://localhost:8090/healthz"
echo "    前端      http://localhost:5173    (手动 npm run dev 后)"
echo "  验收照 docs/superpowers/plans/2026-06-28-omnigent-integration/RUNBOOK.md 走。"
