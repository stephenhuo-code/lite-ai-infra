# Dev Workspace 9d — 工作目录持久化(对象存储)+ 本地 git Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development 或 executing-plans。Steps 用 `- [ ]`。
> **前置**:地基(`2026-06-26-dev-workspace.md`)已合并;建议 9b 已有工作台能驱动会话(git 视图前端在 9b,本计划出后端能力)。

**Goal:** 工作目录**以 workspace 为单位持久化到对象存储、按 owner 隔离**,会话中断/重开内容与版本仍在;agent 默认可读写本 workspace 目录;支持**本地 git**(init/commit/log/回溯)。远端 git 用户自配(不内建)。覆盖 spec US5 + owner 2026-06-26 持久化决策。

**Architecture:** workspace 目录 = OSS 路径 `<企业>/{owner}/workspace/<ws>/`(owner 隔离)。会话建立时**从 OSS 水合**到 omnigent environment 工作目录;变更经 environment changes API 检出后**持久化回 OSS**。git 在工作目录内本地跑(沙箱 shell);git 状态/历史经 MCP/BFF 暴露给左树。

**Tech Stack:** OSS 客户端(复用 `pipelines/data_prep/oss_fetch` 模式)、omnigent environment filesystem API(`/v1/sessions/{id}/resources/environments/{eid}/filesystem*` + `/changes`)、`git`(沙箱内)、`services/gateway/bff`、`services/dev_workspace_mcp`;pytest。

**门禁:** `make test` + `make lint`。

---

## 状态(实时)
> **代码任务完成 ✅(Task 1–5)· 274 passed + lint KEPT · 分支 `dev-workspace-9d`**
> **待交互探针**:Task 0(omnigent environment filesystem 同步形态)+ 真实 OSS↔本地盘 syncer + live runbook —— 需运行中的 omnigent,留与 9b/9d 探针一起跑。

| Task | 状态 | 产物 |
|---|---|---|
| 0 探针(同步形态) | ⏳ 待交互 | —— |
| 1 workspace 路径(owner 隔离) | ✅ | `bff/workspace_store.py` |
| 2 hydrate/persist(注入式) | ✅ | `bff/workspace_store.py` |
| 3 本地 git 工具 | ✅ | `dev_workspace_mcp/tools/git.py` |
| 4 BFF 会话生命周期 | ✅ | `bff/workspace.py`(hydrate/close+revoke) |
| 5 git 工具接入 MCP | ✅ | `app.py`(`liteai__git_*`) |
| 真实 syncer + live | ⏳ 待 Task0 | —— |

---

## File Structure
- `services/gateway/bff/workspace_store.py` — **新增**:workspace OSS 路径派生(owner 隔离)+ 水合/持久化(hydrate/persist,sync 逻辑)。
- `services/dev_workspace_mcp/tools/git.py` — **新增**:`git_status` / `git_log`(读,供左树)+ `git_commit`(写,本地);纯函数 + 注入 runner(执行 git 命令)。
- `services/gateway/bff/workspace.py` — **改**:`create_workspace_session` 增 hydrate 步;新增 `close_workspace_session` 做 persist + 撤销令牌。
- `tests/dev_workspace/test_workspace_store.py` / `test_tool_git.py` — **新增**。

---

## Task 0:探针 — environment 工作目录路径 + 同步形态(外部依赖事实)

> 地基 Task0 已确认沙箱;本探针专钉"omnigent environment 的工作目录在 host 哪个路径、filesystem API 读写形态、changes 检出",决定同步实现。**非 TDD,带决策规则。**

- [ ] **Step 1**:起会话(地基 omnigent.yml + host)→ `GET /v1/sessions/{id}/resources/environments` 看 environment 列表 + 工作目录字段。
- [ ] **Step 2**:`PUT .../filesystem/{relative_path}` 写一个文件,`GET` 读回,`GET .../changes` 看变更检出形态。记真实 req/resp 到 `spikes/2026-06-26-omnigent-probe-RESULTS.md`(追加 9d 节)。
- [ ] **Step 3**:确认 host runner 的 environment 工作目录在宿主的物理路径(可直接挂 OSS)还是只能经 filesystem API 读写。**决策规则**:① 若有物理路径 → 同步用"OSS ↔ 本地目录 rsync 式";② 若只能经 API → 同步用"遍历 filesystem API 读写"(慢但通用)。选定写入 design。
- [ ] **Step 4**:Commit RESULTS 追加。

## Task 1:workspace OSS 路径派生(owner 隔离)

**Files:** Create `services/gateway/bff/workspace_store.py`;Test `tests/dev_workspace/test_workspace_store.py`

- [ ] **Step 1:写失败测试**
```python
# tests/dev_workspace/test_workspace_store.py
import pytest
from services.gateway.bff.workspace_store import workspace_prefix

def test_prefix_is_enterprise_owner_workspace_scoped():
    assert workspace_prefix(enterprise="ent-demo", owner="u-alice", ws="coco-clean") \
        == "ent-demo/u-alice/workspace/coco-clean/"

def test_prefix_rejects_traversal():
    with pytest.raises(ValueError):
        workspace_prefix(enterprise="ent-demo", owner="u-alice", ws="../escape")
```
- [ ] **Step 2:跑(红)。**
- [ ] **Step 3:实现**
```python
# services/gateway/bff/workspace_store.py
# workspace 目录 = OSS 路径 <企业>/{owner}/workspace/<ws>/(owner 隔离,owner 模型 ADR-024)。
# ws 名禁路径穿越(.. / / )防越界到他人前缀。
from __future__ import annotations
import re

_WS_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")

def workspace_prefix(*, enterprise: str, owner: str, ws: str) -> str:
    if not _WS_RE.match(ws):
        raise ValueError(f"invalid workspace name: {ws!r}")
    return f"{enterprise}/{owner}/workspace/{ws}/"
```
- [ ] **Step 4:跑(绿)。** **Step 5:Commit。**

## Task 2:水合 / 持久化(同步逻辑)

> 形态按 Task 0 决策(物理路径 rsync 或 API 遍历)。下方以**注入式 syncer**抽象,单测用 FakeOSS + FakeFS,真实 syncer 实现按 Task0 定。

**Files:** Modify `services/gateway/bff/workspace_store.py`;Test 续 `test_workspace_store.py`

- [ ] **Step 1:写失败测试**
```python
# 追加 tests/dev_workspace/test_workspace_store.py
from services.gateway.bff.workspace_store import hydrate, persist

class FakeOSS:
    def __init__(self, objs): self.objs=dict(objs); self.put=[]
    def list(self, prefix): return [k for k in self.objs if k.startswith(prefix)]
    def get(self, k): return self.objs[k]
    def put_object(self, k, b): self.put.append(k); self.objs[k]=b

class FakeFS:
    def __init__(self): self.files={}
    def write(self, rel, b): self.files[rel]=b
    def read(self, rel): return self.files[rel]
    def listrel(self): return list(self.files)

def test_hydrate_copies_oss_to_fs():
    oss=FakeOSS({"ent-demo/u-alice/workspace/w/recipe.py": b"x"})
    fs=FakeFS()
    n=hydrate(oss, fs, prefix="ent-demo/u-alice/workspace/w/")
    assert n==1 and fs.files["recipe.py"]==b"x"

def test_persist_copies_fs_to_oss_under_prefix():
    oss=FakeOSS({}); fs=FakeFS(); fs.write("recipe.py", b"y")
    persist(oss, fs, prefix="ent-demo/u-alice/workspace/w/")
    assert "ent-demo/u-alice/workspace/w/recipe.py" in oss.objs
```
- [ ] **Step 2:跑(红)。**
- [ ] **Step 3:实现**
```python
# 追加 services/gateway/bff/workspace_store.py
def hydrate(oss, fs, *, prefix: str) -> int:
    n = 0
    for key in oss.list(prefix):
        rel = key[len(prefix):]
        if rel:
            fs.write(rel, oss.get(key)); n += 1
    return n

def persist(oss, fs, *, prefix: str) -> int:
    n = 0
    for rel in fs.listrel():
        oss.put_object(prefix + rel, fs.read(rel)); n += 1
    return n
```
- [ ] **Step 4:跑(绿)。** **Step 5:Commit。**

## Task 3:本地 git 工具(status/log/commit)

**Files:** Create `services/dev_workspace_mcp/tools/git.py`;Test `tests/dev_workspace/test_tool_git.py`

- [ ] **Step 1:写失败测试**(注入 runner,断言生成的 git 命令 + 解析)
```python
# tests/dev_workspace/test_tool_git.py
from services.dev_workspace_mcp.tools.git import git_status, git_commit, parse_status

class FakeRunner:
    def __init__(self, out): self.out=out; self.ran=[]
    def run(self, argv, cwd): self.ran.append((argv,cwd)); return self.out

def test_status_parses_porcelain():
    st = parse_status(" M recipe.py\n?? output/\n")
    assert st == [{"x":"M","path":"recipe.py"},{"x":"?","path":"output/"}]

def test_commit_runs_add_and_commit_local_only():
    r = FakeRunner("")
    git_commit(r, cwd="/ws", message="feat: x")
    cmds = [a for a,_ in r.ran]
    assert ["git","add","-A"] in cmds
    assert any(c[:2]==["git","commit"] and "feat: x" in c for c in cmds)
    assert not any("push" in c for c in cmds)     # 本地 only,绝不 push
```
- [ ] **Step 2:跑(红)。**
- [ ] **Step 3:实现**
```python
# services/dev_workspace_mcp/tools/git.py
# 本地 git(init/commit/log/status);绝不 push(远端 git 用户自配,spec 推迟)。
# runner 注入(沙箱内执行 git);纯解析可单测。
from __future__ import annotations

def parse_status(porcelain: str) -> list[dict]:
    out = []
    for line in porcelain.splitlines():
        if not line.strip():
            continue
        out.append({"x": line[:2].strip()[:1] or "?", "path": line[3:].strip() or line[2:].strip()})
    return out

def git_status(runner, *, cwd: str) -> list[dict]:
    return parse_status(runner.run(["git", "status", "--porcelain"], cwd=cwd))

def git_log(runner, *, cwd: str, n: int = 20) -> str:
    return runner.run(["git", "log", f"-{n}", "--oneline"], cwd=cwd)

def git_commit(runner, *, cwd: str, message: str) -> None:
    runner.run(["git", "add", "-A"], cwd=cwd)
    runner.run(["git", "commit", "-m", message], cwd=cwd)   # 本地;无 push
```
- [ ] **Step 4:跑(绿)。** **Step 5:Commit。**

## Task 4:接入 BFF 会话生命周期(hydrate on open / persist on close)

**Files:** Modify `services/gateway/bff/workspace.py`;Test 续 `test_bff_workspace.py`

- [ ] **Step 1:写失败测试**:`create_workspace_session` 增 `ws` 名 + 调 hydrate(注入 syncer,断言被调用 + 路径=workspace_prefix);新增 `close_workspace_session` 调 persist + `store.revoke_session`。
- [ ] **Step 2:跑(红)。**
- [ ] **Step 3:实现**:在 `create_workspace_session` 用 `workspace_prefix(...)` + `hydrate(...)`(syncer 注入);`close_workspace_session(*, session, store, oss, fs, prefix)` 调 `persist` 再 `store.revoke_session(session)`。git init(若无 `.git`)在 hydrate 后。
- [ ] **Step 4:跑(绿)+ `make lint`。** **Step 5:Commit。**

## Task 5:接入 git 工具到 MCP + live runbook
- [ ] app.py 注册 `git_status`/`git_log`/`git_commit`(`liteai__git_*`,runner=沙箱执行器)。
- [ ] live:工作目录改文件 → `git_commit` → 关会话(persist)→ 重开同 ws(hydrate)→ 文件 + 提交仍在;左树 git 显示状态。

---

## 推迟(v-next)
- 远端 git 托管集成(用户配置);workspace 配额/GC;大文件/二进制 LFS;并发同一 workspace 多会话的合并。

## Self-Review
- 覆盖 US5(持久化 + 本地 git):Task1 owner 隔离路径 / Task2 OSS 水合-持久化 / Task3 本地 git(无 push)/ Task4 会话生命周期 ✓。owner 决策(OSS 为底、按 ws 隔离、默认授权、本地 git、远端用户配)全落。Task0 探针钉同步形态(外部依赖事实)。无 TBD;同步真实实现有 Task0 决策规则 + `oss_fetch` 家兜底。
