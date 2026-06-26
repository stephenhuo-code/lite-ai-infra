# third_party/omnigent — vendored 上游(自构建用,ADR-026 §1 / plan 9-prod)

omnigent 以 git submodule 形式 vendor,**钉定上游源码 ref(不改)**,我们 CI 从清洁 checkout 自构建
`omnigent-server`/`omnigent-host` 镜像推我们 registry(供应链 / 可复现 / 离线 / 打补丁能力位)。

## 添加(采用后/进 prod 前执行一次)
```bash
git submodule add https://github.com/omnigent-ai/omnigent third_party/omnigent
cd third_party/omnigent && git checkout 38523a1143770427585467cc5be2bf18f5f85db7 && cd -
git add .gitmodules third_party/omnigent
git commit -m "build(plan9prod): vendor omnigent @ 38523a1(Task0 实测可用)"
```
> 钉定 ref = `38523a1143770427585467cc5be2bf18f5f85db7`(Task0 探针实测可用,镜像 digest
> `sha256:112be2e5…` 对应)。无 release tag 时锁 commit。

## 升级
```bash
cd third_party/omnigent && git fetch && git checkout <new-tag-or-commit> && cd -
# 若有补丁:见 deploy/omnigent-patches/ 重放
git add third_party/omnigent && git commit -m "build: bump omnigent → <ref>"
# CI 自动重构建推 registry
```
不改源码 → 升级零冲突;改码 → 见 `deploy/omnigent-patches/`。
