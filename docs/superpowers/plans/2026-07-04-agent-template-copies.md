# 企业模板副本(Agent Template Copies)Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把智能体库从「平台内置模板全局共享**只读**」改成「每企业**首次进库**惰性获得**全套模板的可编辑副本**」——企业改的是自己那份,平台模板永不被触碰。

**Architecture:** 在 fork 加一个服务端 clone 端点(`POST /v1/agents/{id}/copy`,忠实复制模板 bundle、换企业前缀名+描述);BFF 在 `GET /v1/ws/agents` 读路径上做**惰性、一次性、系统级**种子(每企业一份文件标记防复活),并把企业侧列表改成**只显示本企业副本**;编辑/删除复用现有本企业路径;前端副本天然可编辑。

**Tech Stack:** Python 3.12 + FastAPI(BFF `services/gateway/bff/` 与 fork `third_party/omnigent/`)、httpx MockTransport 单测、TypeScript + Vite 前端、omnigent fork 模型 C(自编译 `:dev` 镜像 + submodule bump)。

## Global Constraints

- **企业归属编码(ADR-027 as-built)**:SEP = ASCII `_`;`name = "<alias>_<ascii-slug>-<rand>"`;人类展示名落 `description` 首行(`_encode_description`/`_decode_description`)。无前缀 = 内置(全局)。
- **alias 不变量**:`^[a-zA-Z0-9-]+$`(`_`-free),由 `_resolve_ctx` guard 强制(现有,勿改)。
- **红线**:副本**无 per-agent 凭据**(继承全局订阅 / 模型配置注入);授权唯一出入口 = `can()`(用户改/删仍走 `agent:configure/delete` = enterprise-admin);种子系统级、**不过** `can(agent:create)`;前端不可指定"给哪个企业种"(alias 只来自已认证会话)。
- **clone 忠实**:instructions/model/skills/mcp/能力位原样保留;clone 走启动期 `_ensure_builtin_agent`,**不套** `_assert_safe_builtin_spec`(那是防 UNTRUSTED 上传)。
- **测试隔离**:任何命中 `GET /v1/ws/agents` 的测试必须把 `AGENT_SEED_DIR` 指向临时目录,**绝不碰真 `secrets/`**(镜像 `MODEL_CONFIG_DIR` 约定)。
- 需求见 `docs/superpowers/plans/2026-07-04-agent-template-copies/spec.md`;设计见同目录 `design.md`;ADR:`docs/adr/ADR-027-agent-library.md`。

---

## File Structure

- **Fork**:`third_party/omnigent/omnigent/server/routes/builtin_agents.py` — 加 `POST /agents/{id}/copy` + `_rewrite_bundle_name_desc` 助手。
- **Fork 测试**:`third_party/omnigent/tests/server/routes/test_builtin_agents_copy.py`(新)。
- **构建**:`scripts/omnigent_build.sh dev` 重编译;`git submodule` 指针 bump。
- **BFF**:`services/gateway/bff/omnigent_proxy.py` — 加种子标记函数(模块级)+ 种子编排(router 闭包)+ 改 `agents()` 列表语义。
- **BFF 测试**:`tests/gateway/bff/test_agents.py` — 加种子用例 + 改 2 条列表语义用例 + `_env` 加 `AGENT_SEED_DIR` 隔离。
- **前端**:`frontend/src/pages/Agents.tsx`(页面描述文案)、`frontend/src/pages/Agents.test.tsx`(去内置断言);`make fe-build` 重 build dist。
- **文档**:`docs/adr/ADR-027-agent-library.md`(增量节)、`docs/superpowers/plans/2026-06-28-omnigent-integration/RUNBOOK.md`(智能体库验收段)。

---

## Task 1: Fork 服务端 clone 端点 `POST /agents/{id}/copy`

**Files:**
- Modify: `third_party/omnigent/omnigent/server/routes/builtin_agents.py`(在 `create_builtin_agents_router` 内 `POST /agents` 之后加新路由;文件顶部加 helper + 正则)
- Test: `third_party/omnigent/tests/server/routes/test_builtin_agents_copy.py`(新)

**Interfaces:**
- Consumes(fork 现有):`agent_store.get(id) -> Agent|None`(有 `.bundle_location/.session_id/.name`)、`agent_store.get_by_name(name) -> Agent|None`、`artifact_store.get(key) -> bytes`、`_ensure_builtin_agent(agent_store, artifact_store, agent_cache, *, name, bundle_bytes)`、`_to_agent_object(agent, agent_cache) -> AgentObject`、`_require_user(request, auth_provider)`。
- Produces(BFF 依赖):`POST /v1/agents/{id}/copy`,form 字段 `name`(必填,`^[a-zA-Z0-9_-]+$`)+ `description`(选填);200 返回 `AgentObject`(new id + name);404=源不存在/非模板;400=name 非法;500=无 artifact_store。

- [ ] **Step 1: 写失败测试**(clone 保留 harness、改名改描述、幂等、404)

在 `third_party/omnigent/tests/server/routes/test_builtin_agents_copy.py`:

```python
"""Tests for server-side template clone (``POST /v1/agents/{id}/copy``).

Faithful copy: reads a template's stored bundle, rewrites only name
(+ description), re-registers via the same startup seeding. Proves the
copy is a distinct row under the target name with the source harness
preserved (harness comes from the bundle's executor), and that unknown
/ session-scoped ids 404.
"""
from __future__ import annotations

import httpx

from tests.server.helpers import build_agent_bundle


def _bundle(name: str, description: str | None = None) -> bytes:
    return build_agent_bundle(
        name=name,
        description=description,
        executor={"type": "omnigent", "config": {"harness": "claude-native"}},
    )


async def _create(client: httpx.AsyncClient, name: str, description: str | None = None) -> str:
    resp = await client.post(
        "/v1/agents",
        files={"bundle": ("agent.tar.gz", _bundle(name, description), "application/gzip")},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def test_copy_clones_under_target_name_preserving_harness(client: httpx.AsyncClient) -> None:
    src_id = await _create(client, "tmpl-src", description="orig free text")

    resp = await client.post(
        f"/v1/agents/{src_id}/copy",
        data={"name": "ent-aaa_tmpl-src-ab12cd", "description": "客服助手\n\n本企业客服"},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "ent-aaa_tmpl-src-ab12cd"        # 目标名生效
    assert body["description"] == "客服助手\n\n本企业客服"     # 描述被改写
    assert body["harness"] == "claude-native"               # bundle executor 忠实保留
    assert body["id"] != src_id                             # 独立新行

    listed = await client.get("/v1/agents?limit=1000")
    names = [a["name"] for a in listed.json()["data"]]
    assert "ent-aaa_tmpl-src-ab12cd" in names and "tmpl-src" in names   # 源仍在


async def test_copy_without_description_keeps_source_description(client: httpx.AsyncClient) -> None:
    src_id = await _create(client, "tmpl-keep", description="keep me")
    resp = await client.post(f"/v1/agents/{src_id}/copy", data={"name": "ent-aaa_keep-1122ff"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["description"] == "keep me"          # 未传 description → 保留源


async def test_copy_unknown_id_404(client: httpx.AsyncClient) -> None:
    resp = await client.post("/v1/agents/ag_does_not_exist/copy", data={"name": "ent-aaa_x-1"})
    assert resp.status_code == 404, resp.text


async def test_copy_invalid_target_name_4xx(client: httpx.AsyncClient) -> None:
    src_id = await _create(client, "tmpl-badname")
    resp = await client.post(f"/v1/agents/{src_id}/copy", data={"name": "bad name!"})
    assert 400 <= resp.status_code < 500, resp.text
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd third_party/omnigent && uv run pytest tests/server/routes/test_builtin_agents_copy.py -q`
Expected: FAIL(404 / route not found —— 端点尚不存在)

- [ ] **Step 3: 加 helper + 正则**(文件顶部 import 区之后、`_to_agent_object` 附近)

在 `third_party/omnigent/omnigent/server/routes/builtin_agents.py` 顶部已 `import io`? 若无则加 `import io`、`import tarfile`、`import yaml`(与 `import re` 同区);加:

```python
_AGENT_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def _rewrite_bundle_name_desc(bundle_bytes: bytes, new_name: str,
                              new_description: str | None) -> bytes:
    """Return a new ``.tar.gz`` identical to the source except ``config.yaml``'s
    ``name`` (and ``description`` when given) are replaced. Every other file
    and every other spec field (instructions / executor / llm / skills /
    mcp_servers / capabilities) is copied byte-for-byte — a faithful clone.
    """
    out = io.BytesIO()
    with tarfile.open(fileobj=io.BytesIO(bundle_bytes), mode="r:gz") as tin, \
            tarfile.open(fileobj=out, mode="w:gz") as tout:
        for m in tin.getmembers():
            if not m.isfile():
                tout.addfile(m)
                continue
            data = tin.extractfile(m).read()
            if m.name.endswith("config.yaml"):
                spec = yaml.safe_load(data) or {}
                spec["name"] = new_name
                if new_description is not None:
                    spec["description"] = new_description
                data = yaml.safe_dump(spec, allow_unicode=True, sort_keys=False).encode("utf-8")
            info = tarfile.TarInfo(name=m.name)
            info.size = len(data)
            info.mode = m.mode
            tout.addfile(info, io.BytesIO(data))
    return out.getvalue()
```

- [ ] **Step 4: 加 clone 路由**(在 `create_builtin_agents_router` 内、`POST /agents` 之后、`DELETE /agents/{id}` 之前)

顶部 `from fastapi import ...` 追加 `Form`:`from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile`。加路由:

```python
    @router.post("/agents/{agent_id}/copy")
    async def copy_builtin_agent(
        agent_id: str,
        request: Request,
        name: Annotated[str, Form()],
        description: Annotated[str | None, Form()] = None,
    ) -> AgentObject:
        """Clone a template agent's stored bundle under a new name.

        Faithful server-side copy: reads the source template's bundle,
        rewrites only ``name`` (and ``description`` when given), and
        re-registers via the same startup seeding (``_ensure_builtin_agent``)
        — instructions / model / skills / mcp / capabilities preserved.
        The untrusted-upload whitelist (``_assert_safe_builtin_spec``) is
        intentionally NOT applied: the source is an already-registered,
        operator-authored template. Tenant ownership is NOT judged here —
        the BFF supplies the enterprise-prefixed ``name`` and is the trust
        boundary.
        """
        _require_user(request, auth_provider)
        if artifact_store is None:
            raise OmnigentError("Artifact store not configured", code=ErrorCode.INTERNAL_ERROR)
        if not _AGENT_NAME_RE.fullmatch(name):
            raise OmnigentError("invalid target name", code=ErrorCode.INVALID_INPUT)
        src = await asyncio.to_thread(agent_store.get, agent_id)
        if src is None or src.session_id is not None:
            raise OmnigentError(f"agent {agent_id!r} not found", code=ErrorCode.NOT_FOUND)
        src_bytes = await asyncio.to_thread(artifact_store.get, src.bundle_location)
        new_bytes = await asyncio.to_thread(_rewrite_bundle_name_desc, src_bytes, name, description)

        from omnigent.server.app import _ensure_builtin_agent
        await asyncio.to_thread(
            _ensure_builtin_agent, agent_store, artifact_store, agent_cache,
            name=name, bundle_bytes=new_bytes,
        )
        agent = await asyncio.to_thread(agent_store.get_by_name, name)
        if agent is None:  # pragma: no cover — just registered
            raise OmnigentError(f"agent {name!r} not found after copy",
                                code=ErrorCode.INTERNAL_ERROR)
        return _to_agent_object(agent, agent_cache)
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd third_party/omnigent && uv run pytest tests/server/routes/test_builtin_agents_copy.py -q`
Expected: PASS(4 passed)

- [ ] **Step 6: 跑 fork 既有 agent 路由测试确认无回归**

Run: `cd third_party/omnigent && uv run pytest tests/server/routes/test_builtin_agents.py tests/server/routes/test_builtin_agents_create.py -q`
Expected: PASS(全绿)

- [ ] **Step 7: 提交(fork 仓库内)**

```bash
cd third_party/omnigent
git add omnigent/server/routes/builtin_agents.py tests/server/routes/test_builtin_agents_copy.py
git commit -m "feat(liteai-9a): POST /v1/agents/{id}/copy — faithful server-side template clone"
```

---

## Task 2: 重编译 omnigent 镜像 + bump submodule 指针

**Files:**
- Modify: 主仓 submodule 指针 `third_party/omnigent`(gitlink)

**Interfaces:**
- Consumes:Task 1 的 fork commit。
- Produces:主仓 `omnigent-server:dev` 镜像含 copy 端点;submodule 指针指向新 fork commit(他机/CI 可拉)。

- [ ] **Step 1: 自编译 server/host `:dev` 镜像**

Run: `cd /Users/yanwen/Documents/github/lite-ai-infra && scripts/omnigent_build.sh dev`
Expected: 编译成功,`omnigent-server:dev` / `omnigent-host:dev` 更新(host 大、慢;需 Docker ≥12G 内存)。

- [ ] **Step 2: 用新镜像重起 omnigent**

Run: `docker compose -f deploy/dev/omnigent/docker-compose.yml up -d`
Expected: `omnigent-dev-omnigent-1` 重启为 healthy。

- [ ] **Step 3: 冒烟 copy 端点(需 header-trust 身份头)**

Run:
```bash
# 列出一个内置模板 id
TID=$(curl -s -H "X-Forwarded-Email: alice@acme.test" http://127.0.0.1:8900/v1/agents | python3 -c 'import sys,json;print(json.load(sys.stdin)["data"][0]["id"])')
# clone 它
curl -s -o /dev/null -w "copy %{http_code}\n" -X POST \
  -H "X-Forwarded-Email: alice@acme.test" \
  -F "name=ent-smoke_probe-aa11bb" -F "description=烟测\n\n" \
  http://127.0.0.1:8900/v1/agents/$TID/copy
```
Expected: `copy 200`。(验后可 `DELETE /v1/agents/<新id>` 清掉,或忽略——种子标记不影响。)

- [ ] **Step 4: bump submodule 指针 + 提交(主仓)**

```bash
cd /Users/yanwen/Documents/github/lite-ai-infra
git add third_party/omnigent
git commit -m "build(9a): bump omnigent submodule — fork 加 POST /agents/{id}/copy 服务端 clone"
```

---

## Task 3: BFF 种子标记函数(每企业一次性,防复活)

**Files:**
- Modify: `services/gateway/bff/omnigent_proxy.py`(模块级,顶部常量区之后、`make_omnigent_router` 之前加纯函数)
- Test: `tests/gateway/bff/test_agents.py`(加一组直接单测)

**Interfaces:**
- Produces:`_seed_dir() -> Path`、`_seed_done(alias) -> bool`、`_try_claim_seed(alias) -> bool`(原子占坑)、`_finalize_seed(alias, *, count, source_ids, seeded_at)`、`_release_seed_claim(alias)`。标记路径:`<AGENT_SEED_DIR|secrets/agent-seed>/<alias>.json`(最终)/`<alias>.seeding`(锁)。

- [ ] **Step 1: 写失败测试**(占坑一次性 + finalize 落标记 + release)

在 `tests/gateway/bff/test_agents.py` 末尾:

```python
# ===== 种子标记:原子占坑 + 一次性 =====

def test_seed_claim_is_once_and_finalize_marks_done(monkeypatch, tmp_path):
    from services.gateway.bff import omnigent_proxy as op
    monkeypatch.setenv("AGENT_SEED_DIR", str(tmp_path))
    assert op._seed_done("ent-aaa") is False
    assert op._try_claim_seed("ent-aaa") is True      # 首个拿到坑
    assert op._try_claim_seed("ent-aaa") is False     # 第二个抢不到(占坑存在)
    assert op._seed_done("ent-aaa") is False           # 仅占坑,未 finalize
    op._finalize_seed("ent-aaa", count=2, source_ids=["a", "b"], seeded_at="2026-07-04T00:00:00+00:00")
    assert op._seed_done("ent-aaa") is True            # finalize 后 = 已种子
    assert (tmp_path / "ent-aaa.json").exists()
    assert not (tmp_path / "ent-aaa.seeding").exists() # finalize 清掉占坑


def test_seed_release_claim_allows_retry(monkeypatch, tmp_path):
    from services.gateway.bff import omnigent_proxy as op
    monkeypatch.setenv("AGENT_SEED_DIR", str(tmp_path))
    assert op._try_claim_seed("ent-bbb") is True
    op._release_seed_claim("ent-bbb")
    assert op._try_claim_seed("ent-bbb") is True       # 释放后可再占(重试)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/gateway/bff/test_agents.py::test_seed_claim_is_once_and_finalize_marks_done -q`
Expected: FAIL(`AttributeError: _seed_done` / `_try_claim_seed`)

- [ ] **Step 3: 实现标记函数**

在 `services/gateway/bff/omnigent_proxy.py` 顶部加 `import json`、`import os` 与 `from pathlib import Path`(若缺);常量区(`_ENV_REF_RE` 之后)加:

```python
# 种子标记(每企业一次性,防"删光又被种满"复活)。镜像 model_config 的 per-enterprise 文件约定。
_SEED_DIR_DEFAULT = "secrets/agent-seed"


def _seed_dir() -> Path:
    return Path(os.getenv("AGENT_SEED_DIR", _SEED_DIR_DEFAULT))


def _seed_done(alias: str) -> bool:
    return (_seed_dir() / f"{alias}.json").exists()


def _try_claim_seed(alias: str) -> bool:
    """原子占坑:O_EXCL 建 <alias>.seeding。成功=拿到种子权;已存在=别人在种 → False。"""
    d = _seed_dir()
    d.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(d / f"{alias}.seeding"), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return False
    os.close(fd)
    return True


def _finalize_seed(alias: str, *, count: int, source_ids: list[str], seeded_at: str) -> None:
    """落最终标记(原子 rename)+ 清占坑。"""
    d = _seed_dir()
    final = d / f"{alias}.json"
    tmp = d / f"{alias}.json.tmp"
    tmp.write_text(json.dumps({"seeded_at": seeded_at, "count": count,
                               "source_template_ids": source_ids}), encoding="utf-8")
    os.replace(str(tmp), str(final))
    try:
        (d / f"{alias}.seeding").unlink()
    except FileNotFoundError:
        pass


def _release_seed_claim(alias: str) -> None:
    try:
        (_seed_dir() / f"{alias}.seeding").unlink()
    except FileNotFoundError:
        pass
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/gateway/bff/test_agents.py -k seed -q`
Expected: PASS(2 passed)

- [ ] **Step 5: 提交**

```bash
git add services/gateway/bff/omnigent_proxy.py tests/gateway/bff/test_agents.py
git commit -m "feat(9a/template-copies): BFF 种子标记(每企业一次性 O_EXCL 占坑)"
```

---

## Task 4: BFF 惰性种子编排 + 列表只显示本企业副本

**Files:**
- Modify: `services/gateway/bff/omnigent_proxy.py`(`make_omnigent_router` 内加 `_copy_template`/`_seed_if_needed` 闭包;改 `agents()` handler)
- Test: `tests/gateway/bff/test_agents.py`(`_env` 加 `AGENT_SEED_DIR` 隔离 + `_Capture` 支持 copy + 5 条种子用例)

**Interfaces:**
- Consumes:Task 3 的标记函数;现有 `_fetch_agents_raw`、`_client`、`_headers`、`_split_enterprise`、`_enterprise_name`、`_encode_description`、`_decode_description`。
- Produces:`GET /v1/ws/agents` 首次触发种子(每模板一次 `POST {omni}/v1/agents/{id}/copy`),之后只回本企业副本(`builtin` 恒 false)。

- [ ] **Step 1: `_env` 加 AGENT_SEED_DIR 隔离 + `_Capture` 支持 copy**

在 `tests/gateway/bff/test_agents.py` 的 `_env` 里加(用独立 tempdir,隔离真 secrets/):

```python
def _env(monkeypatch):
    monkeypatch.setenv("BFF_SESSION_KEY", KEY.decode())
    monkeypatch.setenv("OIDC_CLIENT_ID", "lite-ai-web")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "s")
    monkeypatch.setenv("OIDC_ISSUER", "http://kc/realms/x")
    monkeypatch.setenv("BFF_REDIRECT_URI", "http://gw/auth/callback")
    import tempfile
    monkeypatch.setenv("AGENT_SEED_DIR", tempfile.mkdtemp())   # 每测试独立种子目录,绝不碰真 secrets/
```

在 `_Capture.handler` 里、`/v1/agents` GET 分支之后加 copy 分支(把新副本 append 进 `_agents`,让种子后的 re-fetch 能看到):

```python
        if path.startswith("/v1/agents/") and path.endswith("/copy") and request.method == "POST":
            # 解析 form(name/description),造一个新副本 append 进列表(模拟 omnigent 注册)
            form = {}
            for kv in request.content.split(b"&"):
                if b"=" in kv:
                    k, _, v = kv.partition(b"=")
                    from urllib.parse import unquote_plus
                    form[unquote_plus(k.decode())] = unquote_plus(v.decode())
            new = {"id": f"ag_copy_{len(self._agents)}", "name": form.get("name", ""),
                   "harness": "claude-native", "description": form.get("description", "")}
            self._agents.append(new)
            return httpx.Response(200, json=new)
```

> 注:BFF 用 `cli.post(..., data=form)` 发 `application/x-www-form-urlencoded`,故按 `&`/`=` 解析。

加一个取 copy 请求的助手(紧邻 `_bundle_posts`):

```python
def _copy_posts(cap: _Capture) -> list[httpx.Request]:
    return [q for q in cap.requests
            if q.url.path.startswith("/v1/agents/") and q.url.path.endswith("/copy")
            and q.method == "POST"]
```

- [ ] **Step 2: 写失败测试**(种子/幂等/成员触发/历史跳过/前缀隔离)

在 `tests/gateway/bff/test_agents.py` 加:

```python
# 只含一个内置模板(无本企业 owned)→ 会触发种子
def _builtin_only():
    return [{"id": BUILTIN_ID, "name": "claude-native-ui", "harness": "claude-native",
             "description": "Built-in Claude template"}]


def test_first_list_seeds_copy_and_hides_builtin(monkeypatch):
    cap = _Capture(agents=_builtin_only())
    c = TestClient(_app(monkeypatch, cap, claims_fn=ADMIN_A))
    r = c.get("/v1/ws/agents", cookies={SESSION_COOKIE: _cookie(_valid_sd())})
    assert r.status_code == 200, r.text
    # 为内置模板发了一次 copy(种子)
    copies = _copy_posts(cap)
    assert len(copies) == 1
    assert copies[0].url.path == f"/v1/agents/{BUILTIN_ID}/copy"
    data = r.json()["data"]
    # 列表只回本企业副本(1 条),内置本身不显示
    assert len(data) == 1
    assert data[0]["enterprise_owned"] is True and data[0]["builtin"] is False


def test_second_list_does_not_reseed(monkeypatch):
    cap = _Capture(agents=_builtin_only())
    c = TestClient(_app(monkeypatch, cap, claims_fn=ADMIN_A))
    c.get("/v1/ws/agents", cookies={SESSION_COOKIE: _cookie(_valid_sd())})   # 首次种
    n_after_first = len(_copy_posts(cap))
    c.get("/v1/ws/agents", cookies={SESSION_COOKIE: _cookie(_valid_sd())})   # 二次
    assert len(_copy_posts(cap)) == n_after_first        # 不再种(标记已在)


def test_member_first_list_triggers_seed(monkeypatch):
    cap = _Capture(agents=_builtin_only())
    c = TestClient(_app(monkeypatch, cap, claims_fn=MEMBER_A))   # 普通成员
    r = c.get("/v1/ws/agents", cookies={SESSION_COOKIE: _cookie(_valid_sd())})
    assert r.status_code == 200
    assert len(_copy_posts(cap)) == 1                     # 系统级种子,不因非 admin 而缺


def test_historical_enterprise_skips_copy(monkeypatch):
    # 已有本企业 owned agent(AGENTA_NAME 前缀 ent-aaa)→ 视为已初始化,跳过复制
    agents = _builtin_only() + [
        {"id": AGENTA_ID, "name": AGENTA_NAME, "harness": "claude-native",
         "description": f"{AGENTA_DISPLAY}\n\nentA 的客服"}]
    cap = _Capture(agents=agents)
    c = TestClient(_app(monkeypatch, cap, claims_fn=ADMIN_A))
    r = c.get("/v1/ws/agents", cookies={SESSION_COOKIE: _cookie(_valid_sd())})
    assert r.status_code == 200
    assert _copy_posts(cap) == []                         # 已有 owned → 不复制
    data = r.json()["data"]
    assert [d["name"] for d in data] == [AGENTA_DISPLAY]  # 只回既有本企业副本


def test_seed_copy_target_name_carries_caller_alias(monkeypatch):
    cap = _Capture(agents=_builtin_only())
    c = TestClient(_app(monkeypatch, cap, claims_fn=ADMIN_A))
    c.get("/v1/ws/agents", cookies={SESSION_COOKIE: _cookie(_valid_sd())})
    from urllib.parse import unquote_plus
    body = _copy_posts(cap)[0].content.decode()
    name = next(unquote_plus(kv.split("=", 1)[1]) for kv in body.split("&") if kv.startswith("name="))
    assert name.startswith(f"{ENTA}{SEP}")               # 前缀=会话 alias,隔离不可伪造
```

- [ ] **Step 3: 跑测试确认失败**

Run: `uv run pytest tests/gateway/bff/test_agents.py -k "seed or first_list or reseed or historical or member_first" -q`
Expected: FAIL(种子未接入 → copy 数为 0 / 列表仍含内置)

- [ ] **Step 4: 实现种子编排 + 改列表语义**

在 `services/gateway/bff/omnigent_proxy.py` 的 `make_omnigent_router` 内,`_audit_agent` 之后、`@router.get("/v1/ws/agents")` 之前加两个闭包:

```python
    def _copy_template(email: str, alias: str, template: dict) -> None:
        # 对一个平台模板发服务端 clone;目标名带会话 alias 前缀(不可伪造),
        # 描述改写为展示名约定(首行=模板名),instructions/skills/mcp 由 fork 忠实保留。
        t_id = template.get("id")
        t_display = template.get("name", "")                 # 内置展示名 = omnigent name
        t_desc = template.get("description", "") or ""
        data = {"name": _enterprise_name(alias, t_display),
                "description": _encode_description(t_display, t_desc)}
        with _client() as cli:
            r = cli.post(f"/v1/agents/{t_id}/copy", data=data, headers=_headers(email))
        if r.status_code >= 400:
            raise RuntimeError(f"copy failed for {t_id}: {r.status_code}")

    def _seed_if_needed(email: str, alias: str) -> JSONResponse | None:
        # 惰性一次性系统级种子:首次进库(无标记)→ 原子占坑 → 复制全套平台模板 → 落标记。
        # 已有本企业 owned agent(历史遗留)→ 只补标记、跳过复制。失败→释放占坑+502。
        if _seed_done(alias):
            return None
        raw = _fetch_agents_raw(email)
        if isinstance(raw, JSONResponse):
            return raw
        already_owned = any(_split_enterprise(a.get("name", ""))[0] == alias for a in raw)
        if not _try_claim_seed(alias):
            return None                                      # 别人在种 → 本次照常列(可能少几条)
        try:
            source_ids: list[str] = []
            if not already_owned:
                for t in raw:
                    if _split_enterprise(t.get("name", ""))[0] is None:   # 仅内置(无前缀)
                        _copy_template(email, alias, t)
                        source_ids.append(t.get("id"))
            _finalize_seed(alias, count=len(source_ids), source_ids=source_ids,
                           seeded_at=datetime.now(timezone.utc).isoformat())
        except Exception:
            _release_seed_claim(alias)
            return JSONResponse(status_code=502, content={"reason": "agent seed failed"})
        return None
```

把 `agents()` handler 整体替换为:

```python
    @router.get("/v1/ws/agents")
    def agents(request: Request):
        # 首次进库惰性种子(系统级)→ 列表只回本企业副本(内置=种子源,企业侧不显示)。
        email, ctx, alias, err = _resolve_ctx(request, claims)
        if err:
            return err
        seed_err = _seed_if_needed(email, alias)
        if seed_err:
            return seed_err
        raw = _fetch_agents_raw(email)
        if isinstance(raw, JSONResponse):
            return raw
        out = []
        for a in raw:
            owner, _ = _split_enterprise(a.get("name", ""))
            if owner != alias:               # 内置(owner=None)与他企业 → 企业侧都不显示
                continue
            display, user_desc = _decode_description(a.get("description", "") or "")
            out.append({"id": a.get("id"), "name": display, "harness": a.get("harness"),
                        "description": user_desc, "builtin": False, "enterprise_owned": True})
        return JSONResponse(status_code=200, content={"data": out})
```

- [ ] **Step 5: 跑新测试确认通过**

Run: `uv run pytest tests/gateway/bff/test_agents.py -k "seed or first_list or reseed or historical or member_first" -q`
Expected: PASS(全绿)

- [ ] **Step 6: 提交**

```bash
git add services/gateway/bff/omnigent_proxy.py tests/gateway/bff/test_agents.py
git commit -m "feat(9a/template-copies): 惰性一次性种子(clone 全套模板为本企业副本)+ 列表只显示本企业"
```

---

## Task 5: 更新旧列表语义测试(内置不再可见)

**Files:**
- Modify: `tests/gateway/bff/test_agents.py`(改 2 条:`test_list_filters_per_enterprise_and_strips_prefix`、`test_list_builtin_visible_to_other_enterprise`)

**Interfaces:**
- Consumes:Task 4 的新列表语义(只回本企业 owned)。

- [ ] **Step 1: 跑全量 test_agents 找出被新语义打破的用例**

Run: `uv run pytest tests/gateway/bff/test_agents.py -q`
Expected: FAIL —— `test_list_filters_per_enterprise_and_strips_prefix`(旧断言内置可见)与 `test_list_builtin_visible_to_other_enterprise`(内置跨企业可见)语义已变。

- [ ] **Step 2: 改 `test_list_filters_per_enterprise_and_strips_prefix`**

用默认 `_Capture()`(含 BUILTIN + AGENTA + AGENTB)。ent-aaa 已有 owned(AGENTA)→ 历史跳过、不复制;列表只回本企业。把该用例断言改为:

```python
def test_list_filters_per_enterprise_and_strips_prefix(monkeypatch):
    cap = _Capture()
    c = TestClient(_app(monkeypatch, cap, claims_fn=ADMIN_A))
    r = c.get("/v1/ws/agents", cookies={SESSION_COOKIE: _cookie(_valid_sd())})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    names = [d["name"] for d in data]
    assert names == [AGENTA_DISPLAY]           # 只回本企业副本(展示名,前缀已剥)
    assert all(d["enterprise_owned"] and not d["builtin"] for d in data)
    assert "claude-native-ui" not in names     # 内置不显示
    assert AGENTB_DISPLAY not in names          # 他企业不可见
    assert _copy_posts(cap) == []               # 已有 owned → 不复制(历史跳过)
```

- [ ] **Step 3: 改 `test_list_builtin_visible_to_other_enterprise` → 内置不可见**

语义反转,重命名并改断言(内置对企业侧不可见):

```python
def test_builtins_not_listed_in_enterprise_view(monkeypatch):
    # 内置模板是种子源,企业侧列表绝不并列显示(改了"内置全局可见"的旧语义)。
    cap = _Capture()
    c = TestClient(_app(monkeypatch, cap, claims_fn=ADMIN_B))
    r = c.get("/v1/ws/agents", cookies={SESSION_COOKIE: _cookie(_valid_sd())})
    assert r.status_code == 200
    names = [d["name"] for d in r.json()["data"]]
    assert "claude-native-ui" not in names      # 内置不显示
    assert names == [AGENTB_DISPLAY]            # 只本企业(ent-bbb)副本
```

- [ ] **Step 4: 跑全量 test_agents 确认全绿**

Run: `uv run pytest tests/gateway/bff/test_agents.py -q`
Expected: PASS(全部通过)

- [ ] **Step 5: 跑其它命中 GET /v1/ws/agents 的测试文件确认无 secrets/ 污染 + 无回归**

Run:
```bash
grep -rln '/v1/ws/agents' tests/ | grep -v test_agents.py
uv run pytest tests/gateway/bff -q
```
Expected: 列出的其它文件若 GET agents,确认其 env 也隔离了 `AGENT_SEED_DIR`(未隔离则照 `_env` 方式补 `monkeypatch.setenv("AGENT_SEED_DIR", tempfile.mkdtemp())`);`tests/gateway/bff` 全绿,且 `git status` 里 `secrets/` 无新增文件。

- [ ] **Step 6: 提交**

```bash
git add tests/gateway/bff/
git commit -m "test(9a/template-copies): 列表语义改为只见本企业副本(内置=种子源不显示)"
```

---

## Task 6: 前端 —— 副本可编辑 + 内置文案 + 重 build

**Files:**
- Modify: `frontend/src/pages/Agents.tsx`(页面描述文案)
- Modify: `frontend/src/pages/Agents.test.tsx`(去"内置卡片"断言,若有)
- Build: `make fe-build`

**Interfaces:**
- Consumes:Task 4 后 `GET /v1/ws/agents` 只回 `enterprise_owned=true` 副本;现有 `AgentCard` 的 `ownEditable = canManage && enterprise_owned && !builtin` 天然对副本显示编辑/删除。

- [ ] **Step 1: 改页面副标题文案**(不再是"内置模板 + 本企业创建")

`frontend/src/pages/Agents.tsx` 里:

```tsx
          <p className="text-sm text-slate-500 mt-0.5">本企业的智能体:首次进入时按平台模板自动生成一套,可自由编辑/删除。对话开始时从中选用。</p>
```

- [ ] **Step 2: 更新前端测试(去内置断言)**

Run: `cd frontend && npx vitest run src/pages/Agents.test.tsx`
Expected: 若有断言"内置卡片无编辑/删除入口",它会因列表不再含内置而失效 → 改为断言"本企业副本卡片对管理员显示编辑/删除、对成员不显示";若原测试不涉内置则无需改。按实际失败项最小改动,重跑至 PASS。

- [ ] **Step 3: 重 build 前端 dist**

Run: `make fe-build`
Expected: `frontend/dist/` 更新(网关 8090 同源发)。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/pages/Agents.tsx frontend/src/pages/Agents.test.tsx frontend/dist
git commit -m "feat(9a/template-copies): 智能体库文案对齐(本企业自动生成可编辑副本)+ 重 build"
```

---

## Task 7: ADR-027 增量节

**Files:**
- Modify: `docs/adr/ADR-027-agent-library.md`(在 §5 之后加 §6 增量)

- [ ] **Step 1: 追加增量节**

在 `docs/adr/ADR-027-agent-library.md` 末尾(现有最后一节之后)加:

```markdown
### 6. 增量(2026-07-04,owner 拍板):内置只读 → 每企业可编辑副本

> owner:"内置的 agent 可以直接编辑或删除;逻辑应是平台模板不变,每个企业启动时默认复制一份,企业改的是自己那份。" 本增量把 §2/§4' 的"内置全局共享**只读**"模型改为"**每企业首次进库惰性获得全套模板的可编辑副本**"。设计见 [`../superpowers/plans/2026-07-04-agent-template-copies/`](../superpowers/plans/2026-07-04-agent-template-copies/)。

- **模型转变**:平台模板降级为**企业侧不可见的种子源**;企业首次进「智能体库」时,BFF 惰性、一次性、系统级地把全套模板复制成本企业前缀 agent。企业可见的皆本企业副本、可编辑可删除。§4' "内置模板不可编辑"**作废**(企业侧已无"内置"这一可操作对象)。
- **新小 fork**:`POST /v1/agents/{id}/copy`(服务端 clone)——读模板存储 bundle、仅改 name(+description)、经启动期 `_ensure_builtin_agent` 重注册,忠实保留 instructions/model/skills/mcp/能力位。**唯一途径**:AgentObject 不暴露 instructions,BFF 无法重搭。延续 §1"小 fork 复用内部逻辑、可 upstream"。
- **种子一次性**:每企业一份文件标记(`AGENT_SEED_DIR/<alias>.json`,O_EXCL 占坑防并发)——删了不复活。历史遗留企业(已有本企业 agent)首次触发**跳过复制、补标记**。
- **授权留痕**:种子系统级、**不过** `can(agent:create)`(内容受信=平台模板、落点受隔离=会话 alias、不放大越权面);用户对副本的改/删仍走 `agent:configure/delete` = enterprise-admin(不变)。
- **不变**:归属编码(SEP=`_`+前缀)、副本无 per-agent 凭据(全局订阅/模型配置注入)、信任边界(BFF 唯一写入/过滤点)。
```

- [ ] **Step 2: 提交**

```bash
git add docs/adr/ADR-027-agent-library.md
git commit -m "docs(ADR-027): 增量 §6 — 内置只读 → 每企业可编辑副本(服务端 clone 种子)"
```

---

## Task 8: 更新验收 RUNBOOK(智能体库段)

**Files:**
- Modify: `docs/superpowers/plans/2026-06-28-omnigent-integration/RUNBOOK.md`(智-1/智-2/智-5 段)

- [ ] **Step 1: 改写智能体库验收段**

把 RUNBOOK "「智能体库」验收" 段的模型描述与智-1/智-2/智-5 改为反映新语义。替换该段导语 + 智-1 为:

```markdown
> **这一段验什么(大白话)**:每个企业**第一次进「智能体库」**,系统会自动按平台模板给它生成一整套**本企业自己的**智能体;企业管理员能**直接编辑或删除**其中任意一个(改的只是自己这份,别的企业和平台模板都不受影响)。普通成员能选用、但没有"新建/编辑/删除"入口。

## 智-1. alice 首次进库 → 自动出现一套可编辑副本 + 直接编辑/删除

**你该看到什么**:
1. 用 `alice`/`alice`(企业管理员)登录 `http://localhost:8090`,首次进「智能体库」。
2. 列表里**自动出现一整套本企业智能体**(内容来自平台模板),每条带「本企业」标记、都有「编辑/删除」。
3. 点某条「编辑」改提示词并保存 → 该条更新;点另一条「删除」→ 它消失。**全程无"内置不可改/不可删"报错**。
4. 刷新页面 → 被删的**不复活**(种子只发生一次)。
```

智-2 保留(选用 + 会话锁定),把"看到 alice 建的客服助手"改为"看到本企业那套副本"。智-5 改为:

```markdown
## 智-5. 副本忠实 + 无 per-agent 凭据 + 自编译生效(引用第 5 步)

**这步在验什么**:副本**忠实**保留模板行为(提示词/技能),且**共用平台全局订阅**、**无 per-agent 凭据**;clone 端点是我们 fork 自编译的(改 fork→重编译→生效,复用第 5 步)。

**你该看到什么**:选一个"源自模板"的副本(如源自 debby 的)开聊,行为与原模板一致;执行者证明发往 omnigent 的是 `POST /v1/agents/{id}/copy`(服务端 clone)、镜像是本地 `:dev`(复用第 5 步,不重复跑)。
```

- [ ] **Step 2: 提交**

```bash
git add docs/superpowers/plans/2026-06-28-omnigent-integration/RUNBOOK.md
git commit -m "docs(runbook): 智能体库验收段对齐 — 首次进库自动生成可编辑副本"
```

---

## Self-Review(写完自查)

- **Spec 覆盖**:US1(首次种副本)=Task 4;US2(编辑/删除副本)=复用现有 PUT/DELETE + Task 6 前端可编辑;US3(不复活)=Task 3 标记 + Task 4 编排 + 测试 `test_second_list_does_not_reseed`;US4(跨企业)=Task 4 `owner==alias` 过滤 + `test_seed_copy_target_name_carries_caller_alias` + Task 1 clone 不判租户由 BFF 前缀保证;US5(成员触发)=`test_member_first_list_triggers_seed`;SC-001~005 分落 Task 1/4 测试 + RUNBOOK;历史遗留=`test_historical_enterprise_skips_copy`。
- **无占位符**:各步含真代码/真命令/预期输出。fork 测试用已存在的 `client`/`build_agent_bundle` fixtures;BFF 测试用已存在的 `_Capture`/`_app`/`_cookie`。
- **类型一致**:`_seed_done`/`_try_claim_seed`/`_finalize_seed(*, count, source_ids, seeded_at)`/`_release_seed_claim`、`_copy_template(email, alias, template)`、`_seed_if_needed(email, alias) -> JSONResponse|None`、clone form 字段 `name`/`description` —— Task 3/4 定义与 Task 1 端点契约、测试调用一致。
- **风险留痕**:Task 5 Step 5 显式扫其它 `GET /v1/ws/agents` 测试的 `AGENT_SEED_DIR` 隔离,防真 `secrets/` 污染;native-ui 类模板(harness 非 `_ALLOWED_HARNESSES`)由 clone 原样复制、不受 BFF create 白名单限制(种子非用户输入)。
