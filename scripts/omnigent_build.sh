#!/usr/bin/env bash
# 自构建 omnigent server/host 镜像 → 推我们 registry(plan 9-prod / ADR-026 §1)。
# 从钉定的 vendored 源码(third_party/omnigent)清洁构建;构建前 apply patch-queue。
# server = 默认 target(runtime),host = --target host(Task0 读 Dockerfile 确认)。
set -euo pipefail
REG="${OMNIGENT_REGISTRY:?set OMNIGENT_REGISTRY (our registry)}"
TAG="${OMNIGENT_TAG:?set OMNIGENT_TAG (e.g. sha-<short> / vX.Y.Z)}"
PLATFORMS="${OMNIGENT_PLATFORMS:-linux/amd64,linux/arm64}"
SRC=third_party/omnigent

git -C "$SRC" checkout -- .                                   # 清洁源
shopt -s nullglob
for p in deploy/omnigent-patches/*.patch; do
  echo "apply $p"; git -C "$SRC" apply "$(cd "$(dirname "$p")" && pwd)/$(basename "$p")"
done

docker buildx build --platform "$PLATFORMS" \
  -f "$SRC/deploy/docker/Dockerfile" --target runtime \
  -t "$REG/omnigent-server:$TAG" "$SRC" --push
docker buildx build --platform "$PLATFORMS" \
  -f "$SRC/deploy/docker/Dockerfile" --target host \
  -t "$REG/omnigent-host:$TAG" "$SRC" --push
echo "pushed $REG/omnigent-{server,host}:$TAG"
