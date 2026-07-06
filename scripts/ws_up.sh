#!/usr/bin/env bash
# Plan 9a Workspace 一键编排:按依赖顺序起全栈 + 等就绪。
#
# 顺序(后者依赖前者就绪):
#   1) deps-dev        —— Keycloak + MinIO 等(docker compose),等 KC 就绪
#   2) provision-orgs  —— 把 alice/bob 以 UNMANAGED 加入企业 org(realm 导入后置备,见 provision_orgs.py)
#   3) omnigent-up     —— 自编译 server+host:dev 镜像 + 起 omnigent server/postgres,等 /health
#   4) 前端 build + services up —— 先 build frontend/dist(网关同源发它,故必须先于网关启动),
#                       再起 uvicorn(含 gateway:8090,带 OMNIGENT_BASE_URL=127.0.0.1:8900),等 /healthz
#   5) 就绪            —— 唯一入口 http://localhost:8090(网关同源发前端 + 登录 + API),不再用 5173
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

echo "==> Provision default enterprise agents"
uv run python "$ROOT/scripts/provision_default_agents.py" --enterprise "${EID:-ent-demo}" --omni-base-url "http://127.0.0.1:8900" || {
  echo "ERROR: 默认 agent 置备失败" >&2; exit 1; }

echo "==> [4/5] 前端 build(frontend/dist)+ services up(uvicorn 含 gateway:8090)"
# 网关同源发 frontend/dist(install_static)。dist 必须先于网关启动存在 ——
# install_static 在网关启动那一刻检查 dist 是否存在,不存在就整段跳过(连 catch-all 都不挂)。
echo "  build 前端 dist:"
( cd "$ROOT/frontend" && npm run build ) || { echo "ERROR: 前端 build 失败" >&2; exit 1; }
# 重启 gateway 以挂载刚 build 的 dist(只在启动时检查;dev_services up 见端口已占会跳过 →
# 故先精确停掉 gateway 让它重起,其它 uvicorn 服务不动)。
pkill -f "uvicorn services.gateway.main:app" 2>/dev/null || true
lsof -nP -iTCP:8090 -sTCP:LISTEN -t 2>/dev/null | xargs -r kill 2>/dev/null || true
sleep 1
bash "$ROOT/scripts/dev_services.sh" up || exit 1
_wait "gateway" "http://localhost:8090/healthz" "" 60 || {
  echo "ERROR: gateway 未就绪;看 .dev/gateway.log" >&2; exit 1; }
# 确认网关确实在同源发前端(dist 已挂载),否则提示需重跑
if curl -fsS "http://localhost:8090/" 2>/dev/null | grep -q '<div id="root">'; then
  echo "  ✓ 网关已同源发前端(8090 发 dist)"
else
  echo "  ⚠ 网关未发前端 —— frontend/dist 可能缺失或网关启动早于 build;重跑 make ws-down && make ws-up" >&2
fi

echo "==> [5/5] 就绪"
echo
echo "==> ws-up 完成。栈就绪:"
echo "    ┌─ 唯一入口(浏览器开这个)──────────────────────────────┐"
echo "    │  http://localhost:8090   控制台 + 登录 + Workspace,同源 │"
echo "    └────────────────────────────────────────────────────────┘"
echo "    登录用 alice/alice 或 bob/bob(会被带去 Keycloak 填密码再弹回 8090)。"
echo "    其余口都是后台依赖、不用直接开:"
echo "      Keycloak http://localhost:8080(身份系统,登录中转) · omnigent :8900 · gateway healthz :8090/healthz"
echo "    注:不再用 vite 5173 —— 网关已在 8090 同源发前端。改前端代码需 \`make fe-build\` 重 build(热更新延后)。"
echo "  验收照 docs/superpowers/plans/2026-06-28-omnigent-integration/RUNBOOK.md 走(入口 = 8090)。"
