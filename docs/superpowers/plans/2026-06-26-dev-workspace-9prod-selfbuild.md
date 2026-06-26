# Dev Workspace 9-prod — omnigent 自构建固化到我们 registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: executing-plans(基础设施类,多为脚本/CI,非 TDD)。Steps 用 `- [ ]`。
> **前置 / 触发条件**:地基 + 9b/9c 验证通过、**决定采用 omnigent** 后,**进 prod 前**做。dev 期仍可用上游预构建镜像(地基 Task 1)。依据 [ADR-026 §1](../../adr/ADR-026-dev-workspace-omnigent.md)。

**Goal:** 从**钉定的上游源码 ref**(不改)自构建 `omnigent-server` + `omnigent-host` 镜像、推我们 registry、dev/prod compose 切到我们镜像;升级 = bump ref + 重构建(零冲突);改码 = 最小 patch-queue。给供应链可控 / 可复现 / 可离线 / 打补丁能力位。

**Architecture:** omnigent 作 git submodule(钉 commit/tag);CI 用其主 Dockerfile(web-builder + python builder,支持 clean checkout)构建两镜像 → 推 `<our-registry>/omnigent-{server,host}:<our-tag>`;compose 改用我们镜像。补丁经 `deploy/omnigent-patches/` 在构建前 apply。

**Tech Stack:** git submodule;docker buildx;我们的 CI(GitHub Actions / 现有 CI);我们的容器 registry;omnigent `deploy/docker/Dockerfile`。

**门禁:** 镜像构建成功 + 起栈 `/healthz` 200 + 地基 RUNBOOK B 在自构建镜像上复跑通过。

---

## File Structure
- `.gitmodules` / `third_party/omnigent` — **新增**:omnigent submodule(钉 Task0 实测 commit/tag)。
- `deploy/omnigent-patches/` — **新增(空目录 + README)**:patch-queue(v1 为空,无改码)。
- `.github/workflows/omnigent-image.yml`(或现有 CI 等价)— **新增**:构建 + 推镜像。
- `deploy/dev/omnigent.yml` — **改**:image 指向我们 registry tag。
- `deploy/prod/omnigent.yml`(或 overlay)— **新增**:prod 形态(内部网络、不发布端口、我们 registry 镜像)。
- `scripts/omnigent_build.sh` — **新增**:本地/CI 共用构建脚本(apply patches → buildx → push)。

---

## Task 1:vendor omnigent(submodule 钉定 ref)
- [ ] **Step 1**:加 submodule 钉到 Task0 实测可用 commit:
  ```bash
  git submodule add https://github.com/omnigent-ai/omnigent third_party/omnigent
  cd third_party/omnigent && git checkout <Task0 digest 对应的 tag/commit> && cd -
  git add .gitmodules third_party/omnigent
  ```
  > ref 取 Task0 RESULTS 顶部 digest 对应的发布 tag(若 digest 无对应 tag,用 `git rev-parse` 锁 commit)。
- [ ] **Step 2**:建空 patch-queue:`deploy/omnigent-patches/README.md` 写明"v1 无改码;新增补丁 = `git format-patch` 放此,构建前按文件名序 apply;每次升级重放、只在改过的行冲突"。
- [ ] **Step 3:Commit** `git commit -m "build(plan9prod): vendor omnigent as pinned submodule"`

## Task 2:构建脚本(apply patches → buildx → push)
- [ ] **Step 1**:写 `scripts/omnigent_build.sh`:
  ```bash
  #!/usr/bin/env bash
  set -euo pipefail
  REG="${OMNIGENT_REGISTRY:?set our registry}"; TAG="${OMNIGENT_TAG:?}"
  SRC=third_party/omnigent
  git -C "$SRC" stash -u || true; git -C "$SRC" checkout -- .   # 干净源
  for p in deploy/omnigent-patches/*.patch; do [ -e "$p" ] && git -C "$SRC" apply "../../$p"; done
  docker buildx build --platform linux/amd64,linux/arm64 \
    -f "$SRC/deploy/docker/Dockerfile" -t "$REG/omnigent-server:$TAG" --target "" "$SRC" --push
  docker buildx build --platform linux/amd64,linux/arm64 \
    -f "$SRC/deploy/docker/Dockerfile" -t "$REG/omnigent-host:$TAG" --target host "$SRC" --push
  ```
  > target 名以 `third_party/omnigent/deploy/docker/Dockerfile` 实际为准(地基 Task0 读过:server 默认 target、host 用 `--target host`)。
- [ ] **Step 2**:本地试构建一个(单平台 arm64 先验):`OMNIGENT_REGISTRY=... OMNIGENT_TAG=test ./scripts/omnigent_build.sh` → 构建成功。
- [ ] **Step 3:Commit** 脚本。

## Task 3:CI 工作流
- [ ] **Step 1**:写 `.github/workflows/omnigent-image.yml`:触发 = submodule ref 变更 / 手动;步骤 = checkout(含 submodule)→ 登录我们 registry → 跑 `scripts/omnigent_build.sh`(TAG=`sha-<short>` + 语义 tag)。
- [ ] **Step 2**:跑一次 CI(或手动触发),确认推出 `omnigent-server`/`omnigent-host` 到我们 registry。
- [ ] **Step 3:Commit。**

## Task 4:compose 切到我们 registry + prod 形态
- [ ] **Step 1**:`deploy/dev/omnigent.yml` 的 image 改 `${OMNIGENT_REGISTRY}/omnigent-server:${OMNIGENT_TAG}`(默认指我们 registry 的钉定 tag)。
- [ ] **Step 2**:新增 `deploy/prod/omnigent.yml`(或 overlay):**不发布端口、内部网络仅 BFF 可达**、我们 registry 镜像、host/runner 服务(`omnigent-host` 镜像)、持久卷 + 真 secret(POSTGRES_PASSWORD / 模型 token 经 secret store)。
- [ ] **Step 3**:起栈 `/healthz` 200。**Commit。**

## Task 5:验收 — 自构建镜像上复跑地基 RUNBOOK
- [ ] **Step 1**:用我们 registry 的镜像起 dev 栈,跑**地基 RUNBOOK 的 B live 集成** + 9c/9d 的 live 段 → 全过(证明自构建镜像功能等价上游)。
- [ ] **Step 2**:文档化**升级流程**:`cd third_party/omnigent && git checkout <new-tag>` → 重放 patches(若有)→ CI 重构建 → 滚动更新。写入 `deploy/omnigent-patches/README.md` 或 `deploy/README`。
- [ ] **Step 3:Commit。**

---

## 推迟(v-next)
- 镜像签名 / SBOM / 漏洞扫描接入(供应链进一步硬化);多 registry 镜像同步;自动追踪上游 release 的 bot。

## Self-Review
- 覆盖 ADR-026 §1 自构建决策:submodule 钉 ref(Task1)+ 构建脚本/CI(Task2-3)+ compose 切换/prod 形态(Task4)+ 等价性验收(Task5)+ 升级/patch-queue 流程 ✓。不预先 fork(patch-queue 空,YAGNI);改码留按需。触发条件明确(采用后/进 prod 前),不阻塞 dev。无 TBD;Dockerfile target 名有 Task0 已读的事实兜底。

---
## 状态(实时)
> **产物完成 ✅(脚本/CI/compose/vendor 步骤;语法+config 校验过)· 分支 `dev-workspace-9prod`**
> **触发条件未到**:实际 submodule vendoring + `docker build`+push 留「**采用后 + 进 prod + registry 凭证**」(需网络/凭证);Task 5 等价性 RUNBOOK 复跑同此。omnigent 源码钉 ref = `38523a1`。
