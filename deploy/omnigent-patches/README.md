# omnigent patch-queue(按需改码,plan 9-prod)

**v1 为空 —— 无改码需求**(认证=header env、UI=自建、数据工具=MCP API,均经配置/API)。

仅当出现 config/API 够不着的真需求,才在此放最小补丁:
- `NN-desc.patch`(`git -C third_party/omnigent format-patch` 产出),按文件名序在构建前 apply。
- 每次升级上游后**重放**全部补丁,只在我们改过的行冲突 → 省着改、补丁越少越平滑。
- 构建脚本 `scripts/omnigent_build.sh` 在 buildx 前自动 apply 本目录 `*.patch`。
