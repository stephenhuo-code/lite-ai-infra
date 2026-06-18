# S1 Plan 6:生成式 SDK + `laictl` CLI(出口⑤ 契约 SDK/CLI 可调)

> **⏸ DEFERRED(2026-06-18,ADR-019)**:owner 决定出口⑤ 改由**真 GUI**(BFF + React/Vite)证明,**跳过 CLI**。本计划推迟为后续 ops/自动化/CI 工具,**不删**(契约/device-flow 分析沉淀复用)。现行 Plan 6 = BFF 后端、Plan 7 = 前端、Plan 8 = Dev Workspace。见 `docs/adr/ADR-019-exit5-gui-bff-resequence.md`。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付 S1 出口⑤ —— 由契约对齐的 **Python SDK + `laictl` CLI**,经 **OIDC device flow** 登录、打 **gateway** 调真服务:`laictl data prepare / list / describe` 三命令成功。手写 `python -m pipelines.data_prep` 正式降级为 ops/debug 后门。

**Architecture:** 沿用项目"**codegen 出 models + 手写薄层**"哲学(同 metadata/gravitino):
- **SDK = 薄 httpx 客户端**,复用既有 `libs/contracts_gen/*` 的 pydantic 模型做请求/响应类型;只打 **gateway 聚合入口**(一个 base_url),带 bearer。**不引入重型 openapi 客户端生成器**(openapi-python-client 对 3 个小契约过重,且会与 contracts_gen 双份模型)——这是本计划的取舍。
- **CLI = `laictl` 包**(stdlib argparse,零额外依赖,同 `__main__.py` 风格),命令薄壳调 SDK。
- **认证 = OIDC device flow**:`laictl login` 走设备码流(无浏览器回调,适合 CLI),token 存 `~/.config/laictl/credentials.json`;后续命令自动带 bearer。
- **新顶层包 `laictl`**:分层 `laictl → libs`(可 import `libs.contracts_gen`/`libs.identity` 只读类型;**不**被 services/pipelines/libs 反向 import)。import-linter 加 `laictl` 根包。
- **命令↔端点(全用现有契约)**:`prepare`→`POST /v1/data/prepare`+轮询`GET /v1/data/jobs/{id}`;`list`→`GET /v1/catalogs/{c}/schemas/{s}/datasets`;`describe`→`…/datasets/{name}`。**不依赖**尚未存在的"列作业"端点(backlog #1)。

**Tech Stack:** Python 3.12、httpx、stdlib argparse、既有 `libs/contracts_gen` models、Keycloak device flow(realm 加公共客户端)、pytest 两层(unit / integration 真服务)。

**端口/入口:** CLI 默认打 `LAICTL_API`(默认 `http://localhost:8090` = gateway);Keycloak `LAICTL_ISSUER`(默认 `http://localhost:8080/realms/lite-ai`);console_scripts `laictl`。

**身份传递:** device flow 拿 access_token → CLI 带 `Authorization: Bearer` 打 gateway → gateway 边缘验签 + 透传 → 下游 can()。CLI 不碰企业/组(从 token 推导,同服务端纪律)。

---

### Task 1:`laictl` 包骨架 + 分层 + console_scripts + 凭据存储(TDD)

**Files:**
- 创建:`laictl/__init__.py`、`laictl/config.py`、`laictl/cli.py`、`tests/laictl/__init__.py`、`tests/laictl/test_config.py`
- 修改:`.importlinter`(加 `laictl` 根包 + 分层)、`pyproject.toml`(`[project.scripts] laictl`)

- [ ] **步骤 1:写失败测试**(凭据读写:存/取/缺失;路径可被 env 覆盖)

```python
# tests/laictl/test_config.py
from laictl.config import Credentials

def test_save_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("LAICTL_HOME", str(tmp_path))
    Credentials.save("tok-abc", refresh="r-1")
    c = Credentials.load()
    assert c.access_token == "tok-abc" and c.refresh_token == "r-1"

def test_load_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("LAICTL_HOME", str(tmp_path))
    assert Credentials.load() is None
```

- [ ] **步骤 2:跑红**;**步骤 3:实现** `config.py`(凭据文件 `$LAICTL_HOME/credentials.json`,默认 `~/.config/laictl`;0600 权限)

```python
# laictl/config.py
from __future__ import annotations
import json, os
from dataclasses import dataclass
from pathlib import Path

def _home() -> Path:
    return Path(os.getenv("LAICTL_HOME", str(Path.home() / ".config" / "laictl")))

def api_base() -> str: return os.getenv("LAICTL_API", "http://localhost:8090")
def issuer() -> str: return os.getenv("LAICTL_ISSUER", "http://localhost:8080/realms/lite-ai")
def client_id() -> str: return os.getenv("LAICTL_CLIENT_ID", "laictl")

@dataclass
class Credentials:
    access_token: str
    refresh_token: str | None = None

    @staticmethod
    def _path() -> Path: return _home() / "credentials.json"

    @classmethod
    def save(cls, access_token: str, refresh: str | None = None) -> None:
        h = _home(); h.mkdir(parents=True, exist_ok=True)
        p = cls._path(); p.write_text(json.dumps({"access_token": access_token, "refresh_token": refresh}))
        os.chmod(p, 0o600)

    @classmethod
    def load(cls) -> "Credentials | None":
        p = cls._path()
        if not p.exists(): return None
        d = json.loads(p.read_text())
        return cls(d["access_token"], d.get("refresh_token"))
```

- [ ] **步骤 4:`.importlinter`** 加 `laictl` 根包;分层契约把 `laictl` 置顶(可 import libs;不被 services/pipelines 反向依赖)。`pyproject.toml` 加 `[project.scripts]\nlaictl = "laictl.cli:main"`。
- [ ] **步骤 5:跑绿 + `uv run lint-imports`(1 kept)**;**步骤 6:提交** `feat(laictl): package skeleton + credentials store + console entry`

---

### Task 2:OIDC device flow 登录 `laictl login`(TDD)

**Files:** 创建:`laictl/auth.py`、`tests/laictl/test_auth.py`

- [ ] **步骤 1:写失败测试**(device flow:拿 device_code → 轮询 → pending 再 success;HTTP 用注入的 fake transport)

```python
# tests/laictl/test_auth.py
import httpx, json
from laictl.auth import device_login

def test_device_login_polls_until_token(monkeypatch, capsys):
    calls = {"n": 0}
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/auth/device"):
            return httpx.Response(200, json={"device_code":"dc","user_code":"WXYZ",
                "verification_uri":"http://kc/device","interval":0})
        # token 端点:首次 pending,第二次成功
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(400, json={"error":"authorization_pending"})
        return httpx.Response(200, json={"access_token":"tok-1","refresh_token":"r-1"})
    tok = device_login(issuer="http://kc/realms/x", client_id="laictl",
                       client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    assert tok["access_token"] == "tok-1"
    assert "WXYZ" in capsys.readouterr().out          # 向用户显示 user_code
```

- [ ] **步骤 2:跑红**;**步骤 3:实现**(POST `/protocol/openid-connect/auth/device` → 提示用户去 verification_uri 输 user_code → 按 interval 轮询 `/token`,处理 `authorization_pending`/`slow_down`)

```python
# laictl/auth.py
from __future__ import annotations
import time
import httpx

_GRANT = "urn:ietf:params:oauth:grant-type:device_code"

def device_login(issuer: str, client_id: str, *, client_factory=lambda: httpx.Client(timeout=15)) -> dict:
    base = issuer.rstrip("/") + "/protocol/openid-connect"
    with client_factory() as c:
        r = c.post(base + "/auth/device", data={"client_id": client_id}); r.raise_for_status()
        d = r.json()
        print(f"\n请在浏览器打开:{d['verification_uri']}\n输入验证码:  {d['user_code']}\n等待授权…")
        interval = max(int(d.get("interval", 5)), 1)
        while True:
            time.sleep(interval)
            t = c.post(base + "/token", data={"grant_type": _GRANT, "device_code": d["device_code"],
                                              "client_id": client_id})
            if t.status_code == 200:
                return t.json()
            err = t.json().get("error")
            if err == "authorization_pending": continue
            if err == "slow_down": interval += 2; continue
            raise RuntimeError(f"device login failed: {err}")
```

- [ ] **步骤 4:`cli.py` 接 `laictl login`**(调 `device_login` → `Credentials.save`);**步骤 5:跑绿**;**步骤 6:提交** `feat(laictl): OIDC device-flow login`

---

### Task 3:薄 SDK(httpx over contracts_gen models,打 gateway,TDD)

**Files:** 创建:`laictl/sdk.py`、`tests/laictl/test_sdk.py`

- [ ] **步骤 1:写失败测试**(SDK 方法:带 bearer、打对路径、解析成 models;用 MockTransport 验请求与反序列化)

```python
# tests/laictl/test_sdk.py
import httpx, json
from laictl.sdk import Client

def _client(handler):
    return Client(base_url="http://gw", token="tok-1",
                  client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler), base_url="http://gw"))

def test_submit_prepare_sends_bearer_and_body():
    seen = {}
    def h(req):
        seen["auth"] = req.headers.get("authorization"); seen["path"] = req.url.path
        seen["body"] = json.loads(req.content)
        return httpx.Response(202, json={"id":"job-1","status":"queued","terminal":False,
            "dataset":"cc3m","group_id":"g-0001","enterprise_id":"e-0001"})
    job = _client(h).submit_prepare(dataset="cc3m", group_id="g-0001", tar_dir="/d")
    assert seen["auth"] == "Bearer tok-1" and seen["path"] == "/v1/data/prepare"
    assert seen["body"]["dataset"] == "cc3m" and job.id == "job-1" and job.terminal is False

def test_list_datasets_parses():
    def h(req):
        return httpx.Response(200, json={"datasets":[{"name":"cc3m","enterprise_id":"e-0001",
            "group_id":"g-0001","scope":"private","location":"s3://b/x.lance"}]})
    out = _client(h).list_datasets(catalog="data", schema="datasets")
    assert out[0].name == "cc3m"
```

- [ ] **步骤 2:跑红**;**步骤 3:实现**(复用 `libs.contracts_gen` 的 `Job`/`Dataset`/`PrepareJobRequest`;`get_job`/`submit_prepare`/`list_datasets`/`get_dataset`;`client_factory` 测试 seam)

```python
# laictl/sdk.py
from __future__ import annotations
import httpx
from libs.contracts_gen.data_pipeline_models import Job, PrepareJobRequest
from libs.contracts_gen.metadata_models import Dataset, DatasetList

class Client:
    def __init__(self, base_url: str, token: str, *, client_factory=None):
        self._base, self._token = base_url.rstrip("/"), token
        self._factory = client_factory or (lambda: httpx.Client(base_url=base_url, timeout=30))

    def _c(self): return self._factory()
    def _h(self): return {"Authorization": f"Bearer {self._token}"}

    def submit_prepare(self, *, dataset: str, group_id: str, tar_dir: str,
                       np: int | None = None, process: list[dict] | None = None) -> Job:
        body = PrepareJobRequest(dataset=dataset, group_id=group_id, tar_dir=tar_dir,
                                 np=np, process=process).model_dump(exclude_none=True)
        with self._c() as c:
            r = c.post("/v1/data/prepare", json=body, headers=self._h()); r.raise_for_status()
            return Job(**r.json())

    def get_job(self, job_id: str) -> Job:
        with self._c() as c:
            r = c.get(f"/v1/data/jobs/{job_id}", headers=self._h()); r.raise_for_status()
            return Job(**r.json())

    def list_datasets(self, *, catalog: str = "data", schema: str = "datasets") -> list[Dataset]:
        with self._c() as c:
            r = c.get(f"/v1/catalogs/{catalog}/schemas/{schema}/datasets", headers=self._h()); r.raise_for_status()
            return DatasetList(**r.json()).datasets

    def get_dataset(self, name: str, *, catalog: str = "data", schema: str = "datasets") -> Dataset:
        with self._c() as c:
            r = c.get(f"/v1/catalogs/{catalog}/schemas/{schema}/datasets/{name}", headers=self._h()); r.raise_for_status()
            return Dataset(**r.json())
```

- [ ] **步骤 4:跑绿**;**步骤 5:提交** `feat(laictl): thin httpx SDK over contract models (via gateway)`

---

### Task 4:`laictl data prepare`(提交 + 轮询到终态,TDD)

**Files:** 修改:`laictl/cli.py`;创建:`tests/laictl/test_cli_prepare.py`

- [ ] **步骤 1:写失败测试**(命令:未登录→提示 login;已登录→调 SDK submit 后轮询 `terminal`;SDK 用 monkeypatch 注入 fake)

```python
# tests/laictl/test_cli_prepare.py
import laictl.cli as cli
from libs.contracts_gen.data_pipeline_models import Job

def test_prepare_polls_to_terminal(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("LAICTL_HOME", str(tmp_path))
    from laictl.config import Credentials; Credentials.save("tok-1")
    seq = [Job(id="job-1",status="running",terminal=False,dataset="cc3m",group_id="g-0001",enterprise_id="e-0001"),
           Job(id="job-1",status="succeeded",terminal=True,dataset="cc3m",group_id="g-0001",enterprise_id="e-0001",
               rows_written=2, lance_uri="s3://b/cc3m.lance")]
    class FakeSDK:
        def submit_prepare(self,**k): return seq[0]
        def get_job(self,i): return seq.pop()  # 第二次 → succeeded
    monkeypatch.setattr(cli, "_sdk", lambda: FakeSDK()); monkeypatch.setattr(cli.time, "sleep", lambda s: None)
    rc = cli.main(["data","prepare","--dataset","cc3m","--group","g-0001","--tar-dir","/d","--wait"])
    assert rc == 0 and "succeeded" in capsys.readouterr().out

def test_requires_login(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("LAICTL_HOME", str(tmp_path))
    rc = cli.main(["data","list"])
    assert rc == 2 and "laictl login" in capsys.readouterr().out
```

- [ ] **步骤 2:跑红**;**步骤 3:实现** `cli.py`(argparse 子命令 `login` / `data {prepare,list,describe}`;`_sdk()` 从 Credentials 构 Client,缺则提示 login;`prepare --wait` 轮询)
- [ ] **步骤 4:跑绿**;**步骤 5:提交** `feat(laictl): data prepare (submit + --wait poll)`

---

### Task 5:`laictl data list` / `describe`(metadata 数据集,TDD)

**Files:** 修改:`laictl/cli.py`;创建:`tests/laictl/test_cli_list.py`

- [ ] **步骤 1:写失败测试**(list 打印数据集名/scope;describe 打印单个详情;fake SDK)

```python
# tests/laictl/test_cli_list.py
import laictl.cli as cli
from libs.contracts_gen.metadata_models import Dataset

def _login(monkeypatch,tmp_path):
    monkeypatch.setenv("LAICTL_HOME",str(tmp_path)); from laictl.config import Credentials; Credentials.save("t")

def test_list(monkeypatch, tmp_path, capsys):
    _login(monkeypatch,tmp_path)
    class S:
        def list_datasets(self,**k): return [Dataset(name="cc3m",enterprise_id="e-0001",group_id="g-0001",scope="private",location="s3://b/x.lance")]
    monkeypatch.setattr(cli,"_sdk",lambda:S())
    assert cli.main(["data","list"])==0 and "cc3m" in capsys.readouterr().out

def test_describe(monkeypatch, tmp_path, capsys):
    _login(monkeypatch,tmp_path)
    class S:
        def get_dataset(self,n,**k): return Dataset(name=n,enterprise_id="e-0001",group_id="g-0001",scope="shared",location="s3://b/x.lance")
    monkeypatch.setattr(cli,"_sdk",lambda:S())
    assert cli.main(["data","describe","cc3m"])==0 and "shared" in capsys.readouterr().out
```

- [ ] **步骤 2:跑红**;**步骤 3:实现**(list/describe 子命令,表格化输出);**步骤 4:跑绿**;**步骤 5:全量 `uv run pytest -q && uv run lint-imports && bash scripts/ci_guards.sh` 绿**;**步骤 6:提交** `feat(laictl): data list / describe`

---

### Task 6:Keycloak realm 加 `laictl` 设备流客户端 + dev 接线 + 文档

**Files:** 修改:`deploy/dev/keycloak/realm-lite-ai.json`(加 `laictl` 公共客户端 + 设备流)、`README.md`(§laictl 用法)、`pipelines/data_prep/__main__.py`(头部注释标注"非产品入口,ops/debug 后门;产品 CLI=laictl")

- [ ] **步骤 1:realm 加客户端**

```json
{ "clientId": "laictl", "publicClient": true, "standardFlowEnabled": false,
  "directAccessGrantsEnabled": false, "redirectUris": [],
  "attributes": { "oauth2.device.authorization.grant.enabled": "true" } }
```
（`make dev-up` 重导 realm 后,设备流端点 `…/auth/device` 对 `client_id=laictl` 生效。）

- [ ] **步骤 2:README** 增 "§ laictl CLI":`laictl login`(设备流)→ `laictl data prepare/list/describe`;env 表(`LAICTL_API`/`LAICTL_ISSUER`/`LAICTL_CLIENT_ID`/`LAICTL_HOME`)。
- [ ] **步骤 3:`__main__.py` 注释降级**为 ops 后门(不删,标注产品入口是 laictl)。
- [ ] **步骤 4:提交** `feat(laictl): keycloak device-flow client + docs + demote ops backdoor`

---

### Task 7:集成(真服务 + 真 token)+ 验收 + 合并

**Files:** 创建:`tests/integration/test_laictl_e2e.py`

- [ ] **步骤 1:集成测试**(标 `integration`;**device flow 交互无法自动化** → 用 gateway 客户端 ROPC(alice/alice,realm 已 `directAccessGrantsEnabled`)拿真 token 注入 SDK,验三命令打真服务:list 见已注册数据集、describe 取详情、prepare(DJ_BIN 桩或真)→ 轮询 succeeded)

```python
# tests/integration/test_laictl_e2e.py
import os, httpx, pytest
from laictl.sdk import Client
pytestmark = pytest.mark.integration

def _ropc_token():
    r = httpx.post("http://localhost:8080/realms/lite-ai/protocol/openid-connect/token",
        data={"grant_type":"password","client_id":"gateway","client_secret":"dev-secret",
              "username":"alice","password":"alice"}); r.raise_for_status(); return r.json()["access_token"]

def test_sdk_list_describe_against_real_services(minio_s3):
    sdk = Client(base_url="http://localhost:8090", token=_ropc_token())
    names = [d.name for d in sdk.list_datasets()]      # 经 gateway → metadata
    # 至少能正常调通(空也算通);若 e2e 前置注册了 cc3m 则应在内
    assert isinstance(names, list)
```
> 说明:`laictl login` 设备流由**人工 runbook** 验(交互)。自动化集成用 ROPC token 验 SDK/命令打真服务链路。

- [ ] **步骤 2:跑** `make up` 后 `uv run pytest -q -m integration`(新 + 既有全绿);`uv run pytest -q && uv run lint-imports && bash scripts/ci_guards.sh` 全绿。
- [ ] **步骤 3:手动验收**(见文末 runbook:真 `laictl login` 设备流 + 三命令打真服务)。贴输出。
- [ ] **步骤 4:requesting-code-review 子代理隔离评审 → 修 Critical/Important(宪法 §3.4/ADR-017)。**
- [ ] **步骤 5:回写状态**(本 plan checkbox + spec §5.3/§9.3 Plan 6 标 ✅ + 出口⑤ ✅ + S1 进度)+ 提交 + 合并。

---

## 验收对照(出口⑤)

| 出口⑤ 要素 | 任务 |
|---|---|
| 契约对齐的 client(复用 contracts_gen models) | Task 3 |
| OIDC device flow 登录 | Task 2 + Task 6(realm 客户端) |
| `laictl data prepare`(打真服务) | Task 4 |
| `laictl data list / describe` | Task 5 |
| 三命令打真服务成功 | Task 7 + runbook |
| 手写 CLI 降级 ops 后门 | Task 6 步骤 3 |

服务化②③/管线① = 已交付(Plan 3/4/5);本计划只加消费侧 SDK/CLI,不动服务。

## 自审记录

- 占位符:无 TBD;device flow 交互不可自动化已如实写明(集成用 ROPC token,设备流人工 runbook 验)。
- 类型一致:SDK 复用 `libs.contracts_gen` 的 `Job/PrepareJobRequest/Dataset/DatasetList`,与服务端同源;CLI→SDK→models 一条链字段对齐。
- 分层:新顶层包 `laictl → libs` 合法(只读 import contracts_gen 类型);`laictl` 不被 services/pipelines/libs 反向 import(import-linter 加根包守)。命令只打 gateway 聚合入口,不直连下游(契约即边界)。
- 范围:list/describe 用现有 metadata 端点、prepare 用现有 data-pipeline 端点;**不依赖** backlog #1"列作业"端点 —— 出口⑤ 不被 S2 缺口阻塞。
- 取舍:不引 openapi-python-client(对 3 小契约过重 + 与 contracts_gen 双份模型);薄 httpx SDK 复用 codegen models 更省、更一致(已在 Architecture 记)。

---

## 手动验收 runbook(实现完成后照此验证)

> 原则(宪法 §3.2):证据先于断言。

**前置:** `make up`(4 服务 + deps);data-pipeline 真 DJ 需 `make dj-setup` + Ray head(见 Plan 5 runbook)。zsh 整段粘贴若报 `parse error near '#'` 先 `setopt interactivecomments`。

**验收 1 — device flow 登录**
```bash
uv run laictl login        # 打印 verification_uri + user_code;浏览器打开输码、用 alice 登录
uv run laictl login        # 或:已登录则提示已有凭据
```
期望:浏览器授权后 CLI 打印"登录成功",`~/.config/laictl/credentials.json` 生成(0600)。

**验收 2 — 三命令打真服务(经 gateway)**
```bash
uv run laictl data list                          # A 列本组数据集(经 gateway→metadata)
uv run laictl data describe cc3m                  # B 取 cc3m 详情(scope/owner/位置)
uv run laictl data prepare --dataset cc3m --group g-0001 \
  --tar-dir /tmp/tars --wait                      # C 提交+轮询到 succeeded(真 DJ)
```
期望:A=列出数据集(或空列表正常返回);B=cc3m 的 scope/owner/`…/cc3m.lance`;C=轮询数轮后 `succeeded` + 打印 `lance_uri`。**这就是出口⑤ 正式验收证据。**

**验收 3 — 隔离/未登录**
```bash
mv ~/.config/laictl/credentials.json{,.bak}; uv run laictl data list   # 期望:提示先 `laictl login`,退出码 2
mv ~/.config/laictl/credentials.json{.bak,}
```

**收尾:** `make down`。
> 此 runbook 是产品 CLI 的验收模板;Plan 7+ 新命令套同款(login 复用)。
