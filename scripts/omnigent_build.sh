#!/usr/bin/env bash
# 从我们 fork 的 omnigent submodule 自编译 server + host 两个镜像(Plan 9a 模型 C)。
#
# 模型 C:omnigent = 我们 fork 作 submodule(third_party/omnigent,branch liteai-9a),
# 直接从 submodule build,**无 patch-queue**——改 omnigent 走 fork 的 git 提交,不是 patch 文件;
# 不依赖上游预构建镜像。
#
# 两个镜像(Dockerfile 两个 target):
#   - server(--target runtime):API server 镜像;**含 docker CLI**,DockerSandboxLauncher 用它起 host 沙箱。
#   - host  (--target host)   :managed 沙箱镜像,被 DockerSandboxLauncher 拉起来跑 agent runner。
#
# 用法:
#   scripts/omnigent_build.sh dev   本地 build server+host,tag :dev,不 push(SKIP_HOST=1 跳 host)
#   scripts/omnigent_build.sh ci    多平台 buildx build + push 到 registry(需 OMNIGENT_REGISTRY/OMNIGENT_TAG)
#
# 环境变量:
#   TAG               dev 模式镜像 tag(默认 dev)
#   SKIP_HOST=1       dev 模式只 build server,跳过 host
#   OMNIGENT_REGISTRY ci 模式 registry 前缀(必填),如 registry.example.com/liteai
#   OMNIGENT_TAG      ci 模式镜像 tag(必填),如 release tag / git sha
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

SUBMODULE="$ROOT/third_party/omnigent"
DOCKERFILE="$SUBMODULE/deploy/docker/Dockerfile"

# 校验:submodule 必须已 checkout(Dockerfile 在则认为 submodule ok)。
if [[ ! -f "$DOCKERFILE" ]]; then
  echo "ERROR: 找不到 $DOCKERFILE" >&2
  echo "       先初始化 submodule: git submodule update --init third_party/omnigent" >&2
  exit 1
fi

case "${1:-}" in
  dev)
    TAG="${TAG:-dev}"
    echo "==> 本地 build omnigent-server:$TAG (--target runtime)"
    docker build -f "$DOCKERFILE" --target runtime \
      -t "omnigent-server:$TAG" "$SUBMODULE"
    if [[ "${SKIP_HOST:-}" == "1" ]]; then
      echo "==> SKIP_HOST=1,跳过 host 镜像"
    else
      echo "==> 本地 build omnigent-host:$TAG (--target host)"
      docker build -f "$DOCKERFILE" --target host \
        -t "omnigent-host:$TAG" "$SUBMODULE"
    fi
    echo "==> done: omnigent-server:$TAG${SKIP_HOST:+ (host skipped)}"
    ;;
  ci)
    REG="${OMNIGENT_REGISTRY:?需设 OMNIGENT_REGISTRY(registry 前缀)}"
    TAG="${OMNIGENT_TAG:?需设 OMNIGENT_TAG(release tag)}"
    PLATFORMS="linux/amd64,linux/arm64"
    echo "==> buildx push $REG/omnigent-server:$TAG ($PLATFORMS, --target runtime)"
    docker buildx build -f "$DOCKERFILE" --target runtime \
      --platform "$PLATFORMS" \
      -t "$REG/omnigent-server:$TAG" \
      --push "$SUBMODULE"
    echo "==> buildx push $REG/omnigent-host:$TAG ($PLATFORMS, --target host)"
    docker buildx build -f "$DOCKERFILE" --target host \
      --platform "$PLATFORMS" \
      -t "$REG/omnigent-host:$TAG" \
      --push "$SUBMODULE"
    echo "==> done: pushed server+host to $REG (tag $TAG)"
    ;;
  *)
    echo "usage: omnigent_build.sh dev|ci" >&2
    exit 1
    ;;
esac
