#!/usr/bin/env bash
# 自构建 omnigent server/host 镜像(plan 9-prod / ADR-026 §1)。单一源:third_party/omnigent(钉定
# 上游 ref)+ deploy/omnigent-patches/(patch-queue)+ 上游 Dockerfile。构建前 apply 补丁。
# 用法:
#   scripts/omnigent_build.sh dev   # 本地单平台 build,load 进本地 docker,不 push(dev:same source)
#   OMNIGENT_REGISTRY=... OMNIGENT_TAG=v1 scripts/omnigent_build.sh ci   # 多平台 build + push(发布制品)
# server = 默认 target(runtime),host = --target host(Task0 读 Dockerfile 确认)。
set -euo pipefail
MODE="${1:-dev}"
SRC=third_party/omnigent
[ -e "$SRC/deploy/docker/Dockerfile" ] || { echo "缺 $SRC(先 git submodule add,见 third_party/README.md)"; exit 1; }

# 清洁源 + 重放 patch-queue(改 omnigent 走这里)
git -C "$SRC" checkout -- . 2>/dev/null || true
shopt -s nullglob
for p in deploy/omnigent-patches/*.patch; do
  echo "apply $p"; git -C "$SRC" apply "$(cd "$(dirname "$p")" && pwd)/$(basename "$p")"
done

DF="$SRC/deploy/docker/Dockerfile"
if [ "$MODE" = "ci" ]; then
  REG="${OMNIGENT_REGISTRY:?set OMNIGENT_REGISTRY (our registry)}"
  TAG="${OMNIGENT_TAG:?set OMNIGENT_TAG (release, e.g. v1 / sha-xxxx)}"
  PLATFORMS="${OMNIGENT_PLATFORMS:-linux/amd64,linux/arm64}"
  docker buildx build --platform "$PLATFORMS" -f "$DF" --target runtime -t "$REG/omnigent-server:$TAG" "$SRC" --push
  docker buildx build --platform "$PLATFORMS" -f "$DF" --target host    -t "$REG/omnigent-host:$TAG"   "$SRC" --push
  echo "pushed $REG/omnigent-{server,host}:$TAG"
else
  # dev:本地单平台,直接进本地 docker(不 push);compose 引这两个本地 tag。
  TAG="${OMNIGENT_TAG:-dev}"
  docker build -f "$DF" --target runtime -t "omnigent-server:$TAG" "$SRC"
  [ "${SKIP_HOST:-0}" = "1" ] || docker build -f "$DF" --target host -t "omnigent-host:$TAG" "$SRC"
  echo "built local omnigent-server:$TAG${SKIP_HOST:+ (host skipped)}"
fi
