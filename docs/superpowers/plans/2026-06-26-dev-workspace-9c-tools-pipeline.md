# Dev Workspace 9c — 数据工具集 + 管线开发 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development 或 executing-plans。Steps 用 `- [ ]`。
> **前置**:地基(`2026-06-26-dev-workspace.md`,Task 0–6)已合并——本计划在其 MCP server(`services/dev_workspace_mcp/`)上加数据工具。

**Goal:** 让 agent 经令牌化 MCP 工具完成"探查采样 → 写并跑数据管线(Data-Juicer / Python)→ 把产物注册回数据目录",数据访问全程 can() 把关(覆盖 spec US4)。

**Architecture:** 数据访问做成我们的 MCP 工具(catalog 采样 / OSS 读 / 注册回 catalog,内调 `can()`,复用 ADR-023 注册 + `pipelines/data_prep`);DJ/Python 的**执行**用 omnigent 沙箱(agent 写文件 + 跑命令),其读写数据经我们的 OSS 工具或工作目录(9d)。

**Tech Stack:** 复用 `services/dev_workspace_mcp`(mcp FastMCP)、`libs.authz.can`、`pipelines/data_prep`(recipe/runner/lance_writer/oss_fetch/paths)、`services/metadata_service`(注册);pytest。

**门禁:** `make test` + `make lint`。

---

## 状态(实时)
> **开发完成 ✅(Task 1–5)· 266 passed + lint KEPT · 分支 `dev-workspace-9c`**
> Task 6 = live runbook(并入 `2026-06-26-dev-workspace/RUNBOOK.md` C 段)。

| Task | 状态 | 产物 |
|---|---|---|
| 1 OSS 越界守卫 | ✅ | `tools/oss.py` |
| 2 catalog_sample | ✅ | `tools/sample.py` |
| 3 register_dataset | ✅ | `tools/register.py` |
| 4 dj_scaffold | ✅ | `tools/pipeline.py` |
| 5 接入 MCP server | ✅ | `app.py`(5 工具 + OSS/Meta 适配) |
| 6 live runbook | ✅ | `RUNBOOK.md` C 段 |

---

## File Structure
- `services/dev_workspace_mcp/tools/sample.py` — **新增**:`read_sample(ctx, gravitino, oss, *, dataset, n)` 采样(can() + 不可归属 fail-closed)。
- `services/dev_workspace_mcp/tools/oss.py` — **新增**:`oss_read(ctx, oss, *, path)` / `oss_list` —— 仅限调用者企业/owner 前缀(`<企业>/{owner}/...`),越界拒。
- `services/dev_workspace_mcp/tools/register.py` — **新增**:`register_processed(ctx, metadata, *, name, location, derived_from, ...)` 复用 catalog-driven 注册(owner=ctx.user)。
- `services/dev_workspace_mcp/tools/pipeline.py` — **新增**:`scaffold_dj_recipe(...)` 生成 DJ recipe 模板到工作目录;`dj_run_spec()` 返回沙箱内运行 DJ 的命令(供 agent 执行,不在 MCP 内跑重活)。
- `services/dev_workspace_mcp/app.py` — **改**:注册上述工具(`catalog_sample` / `oss_read` / `oss_list` / `register_dataset` / `dj_scaffold`)。
- `tests/dev_workspace/test_tool_sample.py` / `test_tool_oss.py` / `test_tool_register.py` / `test_tool_pipeline.py` — **新增**。

---

## Task 1:OSS 前缀越界守卫(承重·安全)

**Files:** Create `services/dev_workspace_mcp/tools/oss.py`;Test `tests/dev_workspace/test_tool_oss.py`

- [ ] **Step 1:写失败测试**
```python
# tests/dev_workspace/test_tool_oss.py
from libs.identity.context import Context, Membership
from libs.identity.ids import EnterpriseId
from services.dev_workspace_mcp.tools.oss import allowed_prefix, oss_read

class FakeOSS:
    def __init__(self, blob=b"hi"): self.blob = blob; self.got = None
    def get(self, path): self.got = path; return self.blob

def _ctx(sub="u-alice", ent="ent-demo"):
    return Context(user=sub, memberships=[Membership(EnterpriseId(ent), "member")])

def test_allowed_prefix_is_enterprise_owner_scoped():
    assert allowed_prefix(_ctx()) == "ent-demo/u-alice/"

def test_oss_read_within_prefix_ok():
    oss = FakeOSS(b"data")
    out = oss_read(_ctx(), oss, path="ent-demo/u-alice/raw/coco/0.tar")
    assert out["bytes_len"] == 4 and oss.got.endswith("0.tar")

def test_oss_read_outside_prefix_denied():
    oss = FakeOSS()
    out = oss_read(_ctx(), oss, path="ent-other/u-eve/secret")
    assert out == {"error": "forbidden"} and oss.got is None   # 未触达存储
```
- [ ] **Step 2:跑(红)** `uv run pytest tests/dev_workspace/test_tool_oss.py -q` → FAIL(无模块)。
- [ ] **Step 3:实现**
```python
# services/dev_workspace_mcp/tools/oss.py
# OSS 读取工具:仅限调用者「企业/owner」前缀(owner 模型 ADR-024),越界 fail-closed。
# 路径隔离在触达存储前完成(与 metadata_service register 的 allowed 前缀同语义)。
from __future__ import annotations
from libs.identity.context import Context
from services._scaffold.auth import enterprise_of

def allowed_prefix(ctx: Context) -> str:
    return f"{enterprise_of(ctx)}/{ctx.user}/"

def oss_read(ctx: Context, oss, *, path: str) -> dict:
    if not path.startswith(allowed_prefix(ctx)):
        return {"error": "forbidden"}          # 越界,不触达存储
    blob = oss.get(path)
    return {"path": path, "bytes_len": len(blob)}

def oss_list(ctx: Context, oss, *, prefix: str = "") -> dict:
    base = allowed_prefix(ctx)
    full = base + prefix.lstrip("/")
    if not full.startswith(base):
        return {"error": "forbidden"}
    return {"prefix": full, "keys": list(oss.list(full))}
```
- [ ] **Step 4:跑(绿)** → PASS(3)。
- [ ] **Step 5:Commit** `git commit -m "feat(plan9c): OSS 读取工具(企业/owner 前缀越界守卫)"`

## Task 2:数据集采样工具 `catalog_sample`

**Files:** Create `services/dev_workspace_mcp/tools/sample.py`;Test `tests/dev_workspace/test_tool_sample.py`

- [ ] **Step 1:写失败测试**
```python
# tests/dev_workspace/test_tool_sample.py
from libs.identity.context import Context, Membership
from libs.identity.ids import EnterpriseId
from services.dev_workspace_mcp.tools.sample import read_sample

class FakeGravitino:
    def __init__(self, fs): self._fs = fs
    def get_fileset(self, *a): return self._fs

_FS = {"name":"coco","properties":{"owner_user":"u-alice","scope":"private","format":"webdataset"},
       "storageLocation":"s3a://lite-ai/ent-demo/u-alice/raw/coco/"}

def _ctx(sub): return Context(user=sub, memberships=[Membership(EnterpriseId("ent-demo"),"member")])

def test_owner_samples_ok():
    out = read_sample(_ctx("u-alice"), FakeGravitino(_FS), dataset="coco", n=2)
    assert out["dataset"]=="coco" and out["n"]==2 and "location" in out

def test_non_owner_private_denied():
    out = read_sample(_ctx("u-eve"), FakeGravitino(_FS), dataset="coco", n=2)
    assert out["error"]=="forbidden"
```
- [ ] **Step 2:跑(红)。**
- [ ] **Step 3:实现**(镜像 `tools/catalog.py` 的 can() 闸;v1 返回定位 + 约定,真采样读 Lance/webdataset 解码 = v-next,显式标注)
```python
# services/dev_workspace_mcp/tools/sample.py
from __future__ import annotations
from libs.authz.engine import can
from libs.authz.types import Resource
from libs.identity.context import Context
from libs.identity.ids import EnterpriseId
from services._scaffold.auth import enterprise_of

def _metalake(ent: str) -> str:
    assert "_" not in ent, ent
    return ent.replace("-", "_")

def read_sample(ctx: Context, gravitino, *, dataset: str, n: int = 5,
                catalog: str = "data", schema: str = "datasets") -> dict:
    ent = enterprise_of(ctx)
    try:
        fs = gravitino.get_fileset(_metalake(ent), catalog, schema, dataset)
    except Exception:
        return {"error": "not_found"}
    p = fs.get("properties", {}); owner = p.get("owner_user")
    if not owner:
        return {"error": "forbidden"}
    if not can(ctx, "dataset.read", Resource(kind="dataset", enterprise_id=EnterpriseId(ent),
                                             scope=p.get("scope","private"), owner=owner)).allow:
        return {"error": "forbidden"}
    # v1:返回定位 + 格式,真解码采样(webdataset/Lance)= v-next(需 reader 依赖)。
    return {"dataset": dataset, "n": n, "format": p.get("format"),
            "location": fs.get("storageLocation",""), "note": "decode-sampling v-next"}
```
- [ ] **Step 4:跑(绿)。** **Step 5:Commit。**

## Task 3:注册产物回 catalog `register_dataset`

**Files:** Create `services/dev_workspace_mcp/tools/register.py`;Test `tests/dev_workspace/test_tool_register.py`

- [ ] **Step 1:写失败测试**
```python
# tests/dev_workspace/test_tool_register.py
from libs.identity.context import Context, Membership
from libs.identity.ids import EnterpriseId
from services.dev_workspace_mcp.tools.register import register_processed

class FakeMeta:
    def __init__(self): self.created=None
    def create(self, **kw): self.created=kw; return {"name":kw["name"],"owner":kw["owner"]}

def _ctx(sub="u-alice"): return Context(user=sub, memberships=[Membership(EnterpriseId("ent-demo"),"member")])

def test_register_within_owner_prefix_ok():
    meta=FakeMeta()
    out=register_processed(_ctx(), meta, name="coco-clean",
        location="s3://lite-ai/ent-demo/u-alice/processed/coco-clean.lance",
        derived_from="coco")
    assert out["owner"]=="u-alice" and meta.created["name"]=="coco-clean"

def test_register_outside_prefix_denied():
    meta=FakeMeta()
    out=register_processed(_ctx(), meta, name="x",
        location="s3://lite-ai/ent-other/u-eve/processed/x.lance", derived_from="coco")
    assert out["error"]=="forbidden" and meta.created is None
```
- [ ] **Step 2:跑(红)。**
- [ ] **Step 3:实现**(复用 catalog-driven 注册语义:processed location 必须落本人 processed/ 前缀,owner=ctx.user;`meta` 为注入的注册客户端 = 调我们 metadata 服务或同进程注册函数)
```python
# services/dev_workspace_mcp/tools/register.py
from __future__ import annotations
from libs.identity.context import Context
from services._scaffold.auth import enterprise_of

def register_processed(ctx: Context, meta, *, name: str, location: str,
                       derived_from: str, fmt: str = "lance") -> dict:
    ent = enterprise_of(ctx)
    allowed = f"s3://lite-ai/{ent}/{ctx.user}/processed/"   # 与 metadata_service 同前缀语义
    if not location.startswith(allowed):
        return {"error": "forbidden"}                       # 越界前缀
    return meta.create(name=name, location=location, owner=ctx.user, enterprise=ent,
                       kind="processed", format=fmt, derived_from=derived_from, scope="private")
```
- [ ] **Step 4:跑(绿)。** **Step 5:Commit。**

## Task 4:DJ recipe 脚手架 + 运行约定 `dj_scaffold`

> DJ/Python 的**执行**在 omnigent 沙箱(agent 写 recipe + 跑 `dj-process`),不在 MCP 内跑重活。本工具只**生成 recipe 模板**到工作目录 + 返回标准运行命令,复用 `pipelines/data_prep/recipe.py` 约定。

**Files:** Create `services/dev_workspace_mcp/tools/pipeline.py`;Test `tests/dev_workspace/test_tool_pipeline.py`

- [ ] **Step 1:写失败测试**
```python
# tests/dev_workspace/test_tool_pipeline.py
from services.dev_workspace_mcp.tools.pipeline import scaffold_dj_recipe, dj_run_command

def test_scaffold_has_dataset_and_export():
    y = scaffold_dj_recipe(dataset="coco", export="output/coco-clean.lance",
                           ops=[{"text_length_filter": {"min_len": 3}}])
    assert "coco" in y and "output/coco-clean.lance" in y and "text_length_filter" in y

def test_run_command_uses_recipe_path():
    cmd = dj_run_command(recipe_path="recipe.py")
    assert "recipe.py" in cmd and "dj-process" in cmd
```
- [ ] **Step 2:跑(红)。**
- [ ] **Step 3:实现**(产出 DJ 配置 YAML 文本 + 运行命令;真实字段以 `pipelines/data_prep/recipe.py` 为准,实现时核对算子名)
```python
# services/dev_workspace_mcp/tools/pipeline.py
from __future__ import annotations
import json

def scaffold_dj_recipe(*, dataset: str, export: str, ops: list[dict], np: int = 4) -> str:
    lines = [f'dataset_path: "{dataset}"', f'export_path: "{export}"', f"np: {np}", "process:"]
    for op in ops:
        (name, params), = op.items()
        lines.append(f"  - {name}:")
        for k, v in params.items():
            lines.append(f"      {k}: {json.dumps(v)}")
    return "\n".join(lines) + "\n"

def dj_run_command(*, recipe_path: str) -> str:
    return f"dj-process --config {recipe_path}"
```
- [ ] **Step 4:跑(绿)。** **Step 5:Commit。**

## Task 5:接入 MCP server + 命名 + 回归

**Files:** Modify `services/dev_workspace_mcp/app.py`

- [ ] **Step 1:在 app.py 注册工具**(`catalog_sample` / `oss_read` / `oss_list` / `register_dataset` / `dj_scaffold`),每个:`ctx=current_context(); if ctx is None: return {"error":"unauthenticated"}; return <pure_fn>(ctx, <client>(), ...)`。客户端复用 `_gravitino()`,新增 `_oss()`(OSS 客户端,env)、`_meta()`(注册客户端)。工具名前缀 `liteai__`(Task0)。
- [ ] **Step 2:跑** `uv run pytest tests/dev_workspace -q && make lint` → 全绿。
- [ ] **Step 3:Commit** `git commit -m "feat(plan9c): 接入数据工具集到 MCP server"`

## Task 6:live runbook(可选)
- [ ] 在地基 RUNBOOK 的 B 上扩:agent "采样 coco → 写 DJ recipe 到工作目录 → 沙箱跑 dj-process → 注册 coco-clean 回 catalog";负例:越界 OSS 路径 / 跨企业注册被拒。

---

## 推迟(v-next)
- 真解码采样(webdataset/Lance reader)、`run_python` 通用执行工具(沙箱直跑即可,先不做 MCP 包装)、产物 num_samples 服务端权威回填(承 ADR-023 §6)。

## Self-Review
- 覆盖 US4(管线 DJ+Python + 注册回 catalog):Task 2 采样 / Task 4 DJ 脚手架 / Task 3 注册 ✓;Python 执行走沙箱(推迟 MCP 包装,显式)。安全:Task 1 OSS 越界 + Task 3 注册越界前缀守卫,复用 owner 模型。无 TBD;"以实现核对"项(DJ 算子名/OSS 客户端构造)有现成家(`pipelines/data_prep`)兜底。
