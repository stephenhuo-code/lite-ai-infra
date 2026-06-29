#!/usr/bin/env bash
# Plan 9a Workspace 一键停:反向顺序停全栈,并清理动态拉起、不在 compose 里的 managed 沙箱容器。
#
# 反向顺序(与 ws_up.sh 相反):
#   1) services down   —— 主机直跑的 uvicorn(含 gateway)
#   2) omnigent down   —— omnigent server/postgres compose
#   3) deps down(dev-down)—— Keycloak + MinIO 等(保数据停,不删卷)
#   4) 清理 managed 沙箱 —— omnigent server 按用户/会话动态 docker run 起来的 host 容器,
#                          名字以 omnigent-managed- 开头,**不在任何 compose 文件里**,故 compose down 不会动它们。
#
# 每步容错(失败不阻断后续):部分已停/未起也能干净跑完。
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MAKE="${MAKE:-make}"

echo "==> [1/4] services down(uvicorn)"
bash "$ROOT/scripts/dev_services.sh" down || true

echo "==> [2/4] omnigent down"
docker compose -f "$ROOT/deploy/dev/omnigent/docker-compose.yml" down || true

echo "==> [3/4] deps down(Keycloak/MinIO,保数据)"
$MAKE dev-down || true

echo "==> [4/4] 清理 managed 沙箱容器(动态拉起、不在 compose 里)"
ids="$(docker ps -aq --filter name=omnigent-managed- 2>/dev/null)"
if [[ -n "$ids" ]]; then
  echo "$ids" | xargs docker rm -f
else
  echo "  无残留 managed 容器"
fi

echo "==> ws-down 完成。前端(npm run dev)请在其终端 Ctrl-C 自行停。"
