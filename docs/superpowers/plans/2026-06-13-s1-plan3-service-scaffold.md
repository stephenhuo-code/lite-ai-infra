# S1 Plan 3:服务脚手架 + Swagger 能力 + gateway 反代壳 + identity-org-service 抽取

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 立起所有后续服务复用的脚手架(契约优先全循环 + Swagger 三层 + 漂移守卫),并用 identity-org-service 抽取 + gateway 反代壳验证它跑通真·多进程微服务形态。

**Architecture:** 真微服务(owner 06-13 决策):每服务独立 uvicorn 进程,gateway HTTP 反代。脚手架 `services/_scaffold/` 提供 app 工厂(模块级 app + /docs)、共享鉴权依赖(JWKS 验签,从 gateway 迁出)、request-id/结构化日志中间件、反代 helper。契约优先:契约(OpenAPI)→ datamodel-codegen 模型 → 手写 router → 漂移守卫(运行时 openapi 的 paths/operations ⊆ 契约,CI 强制)。分层 `services → libs` 不变(`_scaffold` 属 services 层内共享)。

**Tech Stack:** FastAPI、httpx(反代 + 服务间)、datamodel-codegen(仅模型)、pytest 两层、Swagger UI 容器(契约渲染)、uvicorn ×N。

**端口约定:** gateway 8080、identity-org 8001、metadata 8002(Plan 4)、data-pipeline 8003(Plan 5);env `SERVICE_*_URL` 覆盖。

**身份传递:** gateway 边缘验签 → 转发原始 bearer;每下游用共享依赖再验一次(纵深防御)。

---

### Task 1:`services/_scaffold` —— app 工厂 + 中间件(TDD)

**Files:**
- 创建:`services/_scaffold/__init__.py`、`services/_scaffold/app.py`、`tests/scaffold/__init__.py`、`tests/scaffold/test_app.py`

- [ ] **步骤 1:写失败测试**

```python
# tests/scaffold/test_app.py
from fastapi.testclient import TestClient
from services._scaffold.app import make_service_app

def test_app_exposes_docs_and_openapi():
    app = make_service_app(title="t-svc", version="0.1.0")
    c = TestClient(app)
    assert c.get("/openapi.json").status_code == 200
    assert c.get("/docs").status_code == 200
    assert c.get("/healthz").json() == {"status": "ok"}

def test_request_id_echoed_in_response_header():
    app = make_service_app(title="t-svc", version="0.1.0")
    c = TestClient(app)
    r = c.get("/healthz", headers={"x-request-id": "abc-123"})
    assert r.headers["x-request-id"] == "abc-123"

def test_request_id_generated_when_absent():
    app = make_service_app(title="t-svc", version="0.1.0")
    r = TestClient(app).get("/healthz")
    assert len(r.headers["x-request-id"]) >= 8
```

- [ ] **步骤 2:跑红** `uv run pytest tests/scaffold/test_app.py -q` → ModuleNotFoundError

- [ ] **步骤 3:实现**

```python
# services/_scaffold/app.py
from __future__ import annotations
import logging, uuid
from fastapi import FastAPI, Request

log = logging.getLogger("svc")

def make_service_app(title: str, version: str) -> FastAPI:
    """所有服务的统一 app 工厂:/docs + /openapi.json(FastAPI 自带)、
    /healthz、request-id + 结构化日志中间件。模块级 app = make_service_app(...)。"""
    app = FastAPI(title=title, version=version)

    @app.middleware("http")
    async def _request_id(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        log.info("req", extra={"rid": rid, "path": request.url.path, "method": request.method})
        response = await call_next(request)
        response.headers["x-request-id"] = rid
        return response

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    return app
```

- [ ] **步骤 4:跑绿** → 3 passed;**步骤 5:提交** `feat(scaffold): service app factory (/docs, /healthz, request-id)`

---

### Task 2:`_scaffold/auth.py` —— 共享鉴权依赖(从 gateway 迁出,TDD)

**Files:**
- 创建:`services/_scaffold/auth.py`、`tests/scaffold/test_auth.py`
- 删除(迁移后):`services/gateway/deps.py` 的 `context_from_request`(Task 6 改 gateway 时清理)

- [ ] **步骤 1:写失败测试**(沿用 gateway 现有 seam 行为:默认关、坏 JSON→401、无 token→401)

```python
# tests/scaffold/test_auth.py
import json, pytest
from fastapi import FastAPI, Depends, Request
from fastapi.testclient import TestClient
from services._scaffold.auth import context_from_request
from libs.identity.context import Context

def _app():
    app = FastAPI()
    @app.get("/who")
    def who(ctx: Context = Depends(context_from_request)):
        return {"user": ctx.user, "n": len(ctx.memberships)}
    return app

def test_test_claims_seam_off_by_default(monkeypatch):
    monkeypatch.delenv("LITEAI_ALLOW_TEST_CLAIMS", raising=False)
    c = TestClient(_app())
    r = c.get("/who", headers={"x-test-claims": json.dumps({"sub": "u", "groups": []})})
    assert r.status_code == 401

def test_test_claims_seam_on_when_enabled(monkeypatch):
    monkeypatch.setenv("LITEAI_ALLOW_TEST_CLAIMS", "1")
    c = TestClient(_app())
    r = c.get("/who", headers={"x-test-claims": json.dumps({"sub": "u-a", "groups": ["/e-0001/g-0001/members"]})})
    assert r.status_code == 200 and r.json() == {"user": "u-a", "n": 1}

def test_no_bearer_401(monkeypatch):
    monkeypatch.delenv("LITEAI_ALLOW_TEST_CLAIMS", raising=False)
    assert TestClient(_app()).get("/who").status_code == 401
```

- [ ] **步骤 2:跑红**;**步骤 3:实现**(把 `services/gateway/deps.py` 的逻辑原样迁来,保持 issuer/audience env 校验)

```python
# services/_scaffold/auth.py
from __future__ import annotations
import json, os
from fastapi import Request, HTTPException
from libs.identity.context import parse_context, Context
from libs.identity.tokens import verify_and_decode

def context_from_request(request: Request) -> Context:
    raw = request.headers.get("x-test-claims")
    if raw and os.getenv("LITEAI_ALLOW_TEST_CLAIMS", "0") == "1":
        try:
            c = json.loads(raw)
        except ValueError:
            raise HTTPException(status_code=401, detail="invalid test claims")
        return parse_context(sub=c["sub"], groups=c.get("groups", []))
    authz = request.headers.get("authorization", "")
    if not authz.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="unauthenticated")
    try:
        claims = verify_and_decode(authz[7:], jwks_url=os.environ["LITEAI_JWKS_URL"],
                                   audience=os.getenv("LITEAI_TOKEN_AUDIENCE"),
                                   issuer=os.getenv("LITEAI_TOKEN_ISSUER"))
    except Exception:
        raise HTTPException(status_code=401, detail="invalid token")
    return parse_context(sub=claims["sub"], groups=claims.get("groups", []))
```

- [ ] **步骤 4:跑绿** → 3 passed;**步骤 5:提交** `feat(scaffold): shared auth dependency (JWKS + test-claims seam, default-off)`

---

### Task 3:漂移守卫 + `make api-docs`(Swagger L1+L3,TDD)

**Files:**
- 创建:`services/_scaffold/drift.py`、`tests/scaffold/test_drift.py`、`deploy/dev/swagger-ui.yml`
- 修改:`Makefile`(`api-docs` 目标)

- [ ] **步骤 1:写失败测试**(守卫:运行时 openapi 的 path+method 必须 ⊆ 契约)

```python
# tests/scaffold/test_drift.py
import pytest
from services._scaffold.drift import assert_openapi_subset_of_contract

_CONTRACT = {"paths": {"/v1/me/orgs": {"get": {}}, "/v1/x": {"post": {}}}}

def test_passes_when_runtime_is_subset():
    runtime = {"paths": {"/v1/me/orgs": {"get": {}}}}
    assert_openapi_subset_of_contract(runtime, _CONTRACT)  # 不抛

def test_fails_on_uncontracted_route():
    runtime = {"paths": {"/v1/jobs/{ref}": {"delete": {}}}}  # 契约里没有
    with pytest.raises(AssertionError, match="/v1/jobs"):
        assert_openapi_subset_of_contract(runtime, _CONTRACT)

def test_ignores_builtin_paths():
    runtime = {"paths": {"/docs": {"get": {}}, "/openapi.json": {"get": {}}, "/healthz": {"get": {}}}}
    assert_openapi_subset_of_contract(runtime, _CONTRACT)  # 内建路径豁免
```

- [ ] **步骤 2:跑红**;**步骤 3:实现**

```python
# services/_scaffold/drift.py
from __future__ import annotations

_BUILTIN = {"/docs", "/openapi.json", "/redoc", "/healthz", "/docs/oauth2-redirect"}

def assert_openapi_subset_of_contract(runtime: dict, contract: dict) -> None:
    """运行时暴露的 (path, method) 必须都在契约里声明(内建路径豁免)。
    防"有路由无契约"漂移;schema 字段差异不在此守卫范围(仅告警,见 README)。"""
    c_ops = {(p, m) for p, ms in contract.get("paths", {}).items() for m in ms}
    offenders = []
    for p, ms in runtime.get("paths", {}).items():
        if p in _BUILTIN:
            continue
        for m in ms:
            if (p, m) not in c_ops:
                offenders.append(f"{m.upper()} {p}")
    assert not offenders, f"运行时路由未在契约声明: {offenders}"
```

- [ ] **步骤 4:跑绿** → 3 passed
- [ ] **步骤 5:`make api-docs`(Swagger L1:渲染全部契约,不依赖起服务)**

`deploy/dev/swagger-ui.yml`:
```yaml
services:
  swagger-ui:
    image: swaggerapi/swagger-ui:latest
    ports: ["8088:8080"]
    environment:
      URLS: "[{url: '/contracts/identity-org.yaml', name: 'identity-org'}]"
    volumes:
      - ../../contracts/openapi:/usr/share/nginx/html/contracts:ro
```
`Makefile` 追加:
```make
api-docs:         ; docker compose -f deploy/dev/swagger-ui.yml up -d && echo "Swagger UI: http://localhost:8088"
```
(新增契约时在 `URLS` 加一行;Plan 4/5 各自补。)

- [ ] **步骤 6:提交** `feat(scaffold): openapi drift guard + make api-docs (contract swagger)`

---

### Task 4:`identity_org_service` —— 脚手架第一个真实租户(TDD,自带 /docs)

**Files:**
- 创建:`services/identity_org_service/__init__.py`、`services/identity_org_service/app.py`、`services/identity_org_service/main.py`、`tests/services/identity_org/__init__.py`、`tests/services/identity_org/test_me_orgs.py`

- [ ] **步骤 1:写失败测试**(/v1/me/orgs 行为 = 现 gateway 同款;seam 开启下)

```python
# tests/services/identity_org/test_me_orgs.py
import json, pytest
from fastapi.testclient import TestClient

@pytest.fixture(autouse=True)
def _seam(monkeypatch): monkeypatch.setenv("LITEAI_ALLOW_TEST_CLAIMS", "1")

def _client():
    from services.identity_org_service.app import app
    return TestClient(app)

def _hdr(sub, groups): return {"x-test-claims": json.dumps({"sub": sub, "groups": groups})}

def test_me_orgs_contract_shape():
    r = _client().get("/v1/me/orgs", headers=_hdr("u-alice", ["/e-0001/g-0001/members"]))
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"user", "is_platform_admin", "memberships"}
    assert body["memberships"][0] == {"enterprise_id": "e-0001", "group_id": "g-0001", "role": "member"}

def test_me_orgs_unauthenticated_401():
    import os; os.environ.pop("LITEAI_ALLOW_TEST_CLAIMS", None)
    assert _client().get("/v1/me/orgs").status_code == 401

def test_docs_available():
    assert _client().get("/docs").status_code == 200
```

- [ ] **步骤 2:跑红**;**步骤 3:实现**(用脚手架工厂 + 共享鉴权;模块级 `app`)

```python
# services/identity_org_service/app.py
from fastapi import Depends
from libs.identity.context import Context
from services._scaffold.app import make_service_app
from services._scaffold.auth import context_from_request

app = make_service_app(title="identity-org-service", version="0.1.0")

@app.get("/v1/me/orgs")
def me_orgs(ctx: Context = Depends(context_from_request)):
    return {"user": ctx.user, "is_platform_admin": ctx.is_platform_admin,
            "memberships": [{"enterprise_id": m.enterprise_id, "group_id": m.group_id,
                             "role": m.role} for m in ctx.memberships]}
```

```python
# services/identity_org_service/main.py   启动:uvicorn services.identity_org_service.main:app --port 8001
from services.identity_org_service.app import app  # noqa: F401(env 在进程注入)
```

- [ ] **步骤 4:跑绿** → 3 passed
- [ ] **步骤 5:漂移守卫接入此服务**(测试断言其 openapi ⊆ identity-org.yaml)

```python
# 追加到 tests/services/identity_org/test_me_orgs.py
import yaml, pathlib
from services._scaffold.drift import assert_openapi_subset_of_contract

def test_runtime_matches_contract():
    contract = yaml.safe_load(pathlib.Path("contracts/openapi/identity-org.yaml").read_text())
    runtime = _client().app.openapi()
    assert_openapi_subset_of_contract(runtime, contract)
```
（若 `/healthz` 等触发,确认 drift 的 `_BUILTIN` 已豁免;此测试就是 L3 漂移守卫的活样例。）

- [ ] **步骤 6:`make api-docs` 的 URLS 不变(契约同名);提交** `feat(identity-org-service): extract /v1/me/orgs onto scaffold (+drift guard)`

---

### Task 5:`_scaffold/proxy.py` —— gateway 反代 helper(TDD,用 stub 下游验证)

**Files:**
- 创建:`services/_scaffold/proxy.py`、`tests/scaffold/test_proxy.py`

- [ ] **步骤 1:写失败测试**(stub 下游:一个 scaffold app;验证转发路径/方法/bearer/状态码透传)

```python
# tests/scaffold/test_proxy.py
import pytest, httpx
from fastapi import Request
from fastapi.testclient import TestClient
from services._scaffold.app import make_service_app
from services._scaffold.proxy import mount_proxy

def _downstream():
    app = make_service_app("stub", "0.1.0")
    @app.get("/v1/me/orgs")
    def echo(request: Request):
        return {"saw_auth": request.headers.get("authorization", ""), "path": "/v1/me/orgs"}
    return app

def test_proxy_forwards_path_and_bearer():
    down = _downstream()
    # 用 ASGITransport 把 stub 当作下游;proxy 以可注入的 client 调用
    transport = httpx.ASGITransport(app=down)
    gw = make_service_app("gw", "0.1.0")
    mount_proxy(gw, prefix="/v1/me", base_url="http://down", client_factory=lambda: httpx.Client(transport=transport, base_url="http://down"))
    r = TestClient(gw).get("/v1/me/orgs", headers={"authorization": "Bearer tok-1"})
    assert r.status_code == 200
    assert r.json()["saw_auth"] == "Bearer tok-1"
    assert r.json()["path"] == "/v1/me/orgs"
```

- [ ] **步骤 2:跑红**;**步骤 3:实现**(httpx 转发;bearer 透传;状态码/响应体回传;`client_factory` 为测试 seam,生产默认真 httpx.Client)

```python
# services/_scaffold/proxy.py
from __future__ import annotations
import httpx
from fastapi import FastAPI, Request, Response

def mount_proxy(app: FastAPI, prefix: str, base_url: str, client_factory=None):
    """把 prefix 下所有方法反代到 base_url(保留路径、转发 bearer/x-request-id)。
    client_factory 仅测试注入(ASGITransport);生产用真 httpx.Client(base_url)。"""
    _factory = client_factory or (lambda: httpx.Client(base_url=base_url, timeout=30))

    @app.api_route(prefix + "/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
    def _forward(path: str, request: Request):
        fwd_headers = {}
        for h in ("authorization", "x-request-id", "content-type", "x-test-claims"):
            if h in request.headers:
                fwd_headers[h] = request.headers[h]
        body = b""  # 同步读 body
        with _factory() as client:
            up = client.request(request.method, request.url.path,
                                params=dict(request.query_params), headers=fwd_headers,
                                content=body)
        return Response(content=up.content, status_code=up.status_code,
                        media_type=up.headers.get("content-type"))
```
> 注:同步 body 读取在 v1 GET/查询足够;Plan 5 引入 POST 大 body 时改 async streaming(届时 plan 注明)。

- [ ] **步骤 4:跑绿** → 1 passed;**步骤 5:提交** `feat(scaffold): reverse-proxy helper (bearer pass-through, injectable client)`

---

### Task 6:gateway → 反代壳(TDD;移除示例路由 + 重置测试)

**Files:**
- 重写:`services/gateway/app.py`(纯反代壳)、`services/gateway/main.py`
- 删除:`services/gateway/deps.py`(逻辑已迁 scaffold)、`services/gateway/app.py` 旧的 `/v1/jobs`+`/v1/me/orgs`+`_parse_job_ref`
- 重写:`tests/gateway/test_gateway.py`(改为反代壳测试)

- [ ] **步骤 1:写失败测试**(gateway 边缘验签 + 路由表转发;identity 路径代理到下游 stub)

```python
# tests/gateway/test_gateway.py  (整体替换)
import httpx
from fastapi.testclient import TestClient
from services._scaffold.app import make_service_app
from services.gateway.app import build_gateway

def _identity_stub():
    app = make_service_app("identity-stub", "0.1.0")
    @app.get("/v1/me/orgs")
    def me(): return {"user": "u-proxied", "is_platform_admin": False, "memberships": []}
    return app

def _gw():
    stub = _identity_stub()
    transport = httpx.ASGITransport(app=stub)
    return build_gateway(routes={"/v1/me": ("http://identity", lambda: httpx.Client(transport=transport, base_url="http://identity"))})

def test_gateway_proxies_identity_route():
    r = TestClient(_gw()).get("/v1/me/orgs")
    assert r.status_code == 200 and r.json()["user"] == "u-proxied"

def test_gateway_healthz():
    assert TestClient(_gw()).get("/healthz").json() == {"status": "ok"}

def test_gateway_unknown_route_404():
    assert TestClient(_gw()).get("/v1/nope").status_code == 404
```

- [ ] **步骤 2:跑红**;**步骤 3:实现**(gateway = scaffold app + 按路由表挂反代;真启动从 env 读下游 URL)

```python
# services/gateway/app.py  (整体替换)
from __future__ import annotations
from services._scaffold.app import make_service_app
from services._scaffold.proxy import mount_proxy

def build_gateway(routes: dict) -> "FastAPI":
    """routes: {prefix: (base_url, client_factory|None)}。gateway 是纯反代壳:
    /docs+/healthz 来自脚手架;业务路由全部转发到下游服务。边缘鉴权由下游共享依赖执行
    (gateway 透传 bearer);v2 可在此加边缘预校验/限流。"""
    app = make_service_app(title="api-gateway", version="0.1.0")
    for prefix, spec in routes.items():
        base_url, factory = spec if isinstance(spec, tuple) else (spec, None)
        mount_proxy(app, prefix=prefix, base_url=base_url, client_factory=factory)
    return app
```

```python
# services/gateway/main.py   启动:uvicorn services.gateway.main:app --port 8080
import os
from services.gateway.app import build_gateway

app = build_gateway(routes={
    "/v1/me": os.environ.get("IDENTITY_ORG_URL", "http://localhost:8001"),
    # Plan 4/5 追加:"/v1/datasets"->METADATA_URL、"/v1/data"->DATA_PIPELINE_URL
})
```

- [ ] **步骤 4:跑绿** → 3 passed;`rm services/gateway/deps.py`
- [ ] **步骤 5:全量 + 分层 + 护栏** `uv run pytest -q && uv run lint-imports && bash scripts/ci_guards.sh` 全绿
  - 注:原 `test_addressing_style_*`/`oss_boto3_config` 测试在 gateway 测试文件里——迁到 `tests/audit/`(它们测的是 `libs/audit`,本就该在那)。
- [ ] **步骤 6:提交** `refactor(gateway): reverse-proxy shell (remove demo routes, deps→scaffold)`

---

### Task 7:本地多进程编排 `make run-all` + README

**Files:**
- 修改:`Makefile`(`run-all` / `run-gateway` / `run-identity`)、`README.md`(§微服务本地运行)

- [ ] **步骤 1:Makefile 目标**

```make
run-identity:     ; LITEAI_JWKS_URL=$(JWKS) uv run uvicorn services.identity_org_service.main:app --port 8001 --reload
run-gateway:      ; IDENTITY_ORG_URL=http://localhost:8001 uv run uvicorn services.gateway.main:app --port 8080 --reload
run-all:          ; @echo "起 Keycloak: make dev-up; 然后另开终端分别 make run-identity / make run-gateway"
```
（v1 不引入 Procfile/honcho;`run-all` 给指引,各服务各终端起,日志清晰。Plan 4/5 追加 run-metadata/run-data-pipeline。）

- [ ] **步骤 2:README 增"§ 微服务本地运行"**:端口表(gateway 8080 / identity 8001 / metadata 8002 / data-pipeline 8003)、`make dev-up` + 各 `make run-*`、`make api-docs` 看契约、各服务 `http://localhost:<port>/docs` 看运行时。
- [ ] **步骤 3:手动验证(真·两进程端到端)** —— 终端 A `make dev-up`;B `make run-identity`;C `make run-gateway`;然后:
  ```bash
  TOKEN=$(curl -fsS -d client_id=gateway -d client_secret=dev-secret -d username=alice -d password=alice \
    -d grant_type=password http://localhost:8080/realms/lite-ai/protocol/openid-connect/token | \
    uv run python -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')   # 注:KC 仍在 8080?见下
  curl -fsS -H "Authorization: Bearer $TOKEN" http://localhost:8080/v1/me/orgs
  # 期望:经 gateway(8080)反代到 identity-org(8001)→ 返回 alice 的 memberships
  ```
  > **端口冲突修正**:Keycloak 占 8080,gateway 也想要 8080 → 本计划把 **gateway 改 8090**(env `GATEWAY_PORT`),README 端口表同步。dev Keycloak 维持 8080。
- [ ] **步骤 4:提交** `feat(dev): make run-* multi-process orchestration + README service ports`

---

### Task 8:CI 集成 —— 两服务漂移守卫 + 反代端到端

**Files:**
- 修改:`.github/workflows/ci.yml`(build job 已含 pytest,确认 scaffold/services 测试被收集)
- 创建:`tests/integration/test_gateway_proxy.py`(真起 identity-org 子进程 + gateway 代理,或 ASGI 双 app 串联)

- [ ] **步骤 1:集成测试**(标 `integration`;ASGI 串联两 app,验证 gateway→identity 全链路 + 漂移守卫双服务）

```python
# tests/integration/test_gateway_proxy.py
import httpx, pytest, os
from fastapi.testclient import TestClient
pytestmark = pytest.mark.integration

def test_gateway_to_identity_end_to_end(monkeypatch):
    monkeypatch.setenv("LITEAI_ALLOW_TEST_CLAIMS", "1")
    from services.identity_org_service.app import app as identity_app
    from services.gateway.app import build_gateway
    transport = httpx.ASGITransport(app=identity_app)
    gw = build_gateway(routes={"/v1/me": ("http://id", lambda: httpx.Client(transport=transport, base_url="http://id"))})
    import json
    r = TestClient(gw).get("/v1/me/orgs", headers={"x-test-claims": json.dumps({"sub":"u-a","groups":["/e-0001/g-0001/members"]})})
    assert r.status_code == 200 and r.json()["memberships"][0]["enterprise_id"] == "e-0001"
```
> 说明:此测试用 ASGI 串联(非真两进程)以在 CI 稳定运行;真·两进程端到端属 Task 7 步骤 3 的本地手动验收。

- [ ] **步骤 2:跑** `uv run pytest -q -m integration`(需 `make dev-up`?本测试用 seam+ASGI,无需真 KC/MinIO,可纯 CI)→ 绿
- [ ] **步骤 3:确认 build job 收集 scaffold/services 测试;提交** `test(ci): gateway↔identity proxy e2e + drift guards`

---

## 验收对照

| 目标 | 任务 |
|---|---|
| 服务脚手架(app 工厂 + 鉴权 + 中间件) | Task 1/2 |
| Swagger L1(契约渲染) | Task 3(`make api-docs`) |
| Swagger L2(每服务 /docs) | Task 1(工厂自带)+ Task 4 验证 |
| Swagger L3(漂移守卫 CI) | Task 3 + Task 4/8 接入 |
| identity-org-service 独立(owner 决策 1) | Task 4 |
| gateway 反代壳 + 真微服务拓扑 | Task 5/6/7 |
| 手写 CLI 降级(owner 决策 2) | 不在本计划——`pipelines/data_prep/__main__.py` 注释标注于 Plan 6(产品 CLI 落地时) |

metadata-service = Plan 4(出口②);data-pipeline-service = Plan 5;SDK/CLI = Plan 6。

## 自审记录

- 占位符:无 TBD;每步含完整代码/命令/期望
- 端口冲突:Task 7 步骤 3 发现 gateway 与 Keycloak 抢 8080 → 已就地修正为 gateway 8090(env 可配),README 端口表同步
- 类型一致:`make_service_app`/`context_from_request`/`mount_proxy`/`build_gateway`/`assert_openapi_subset_of_contract` 签名在各 Task 调用处一致
- 迁移完整性:gateway `deps.py` 逻辑迁 `_scaffold/auth.py`(Task 2)后删除(Task 6);`libs/audit` 寻址测试从 gateway 测试文件迁回 `tests/audit/`(Task 6 步骤 5)
- 分层:`_scaffold` 在 services 层内,import `libs` 合法;不被 pipelines/libs 反向 import

---

## 手动验收 runbook(实现完成后照此验证)

> 原则(宪法 §3.2):证据先于断言。

**一键起全部(deps 容器 + 全服务进程):**
```bash
make up      # Keycloak/MinIO + identity-org(8001) + gateway(8090) 一条命令全起
make ps      # 确认 gateway/identity 都"运行中"
```
> 首次或刚 `make down` 后,Keycloak 需 ~25s 导入 realm;`make ps` 显示服务起来即可,token 步骤前确认 `curl -fsS http://localhost:8080/realms/lite-ai/.well-known/openid-configuration` 返回 200。

**验收 1 — Swagger**
- 聚合契约(一个页面看全部 API):`make api-docs` → http://localhost:8088 顶部下拉(自动发现 contracts/;现 1 个 identity-org,Plan 4/5 后变多)
- 运行时 /docs:http://localhost:8090/docs(gateway)、http://localhost:8001/docs(identity,见 `GET /v1/me/orgs`)

**验收 2 — 端到端(经 gateway 反代,真 token 解析)**
```bash
TOKEN=$(curl -fsS -d client_id=gateway -d client_secret=dev-secret -d username=alice \
  -d password=alice -d grant_type=password \
  http://localhost:8080/realms/lite-ai/protocol/openid-connect/token \
  | uv run python -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
curl -fsS -H "Authorization: Bearer $TOKEN" http://localhost:8090/v1/me/orgs; echo   # A
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8090/v1/me/orgs            # B 无 token
curl -s http://localhost:8090/healthz -w " gw\n"; curl -s http://localhost:8001/healthz -w " id\n"  # C
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8090/v1/nope               # D 未知路由
```
期望:A=alice 的 memberships(`e-0001/g-0001/member`);B=`401`;C=两个 `{"status":"ok"}`;D=`404`。
**关键:请求打 gateway 8090,结果由 identity-org 8001 产生 → 反代通。**

**验收 3 — 漂移守卫**
```bash
uv run pytest tests/scaffold/ tests/services/identity_org/ -q   # 期望全 passed
```
`test_runtime_matches_contract` = "运行时路由 ⊆ 契约"活样例(防有路由无契约)。

**收尾**:`make down`(停全部服务 + deps);`make api-docs-down`(停 Swagger UI)。
> 单服务调试用 `make run-identity`/`make run-gateway`(前台 + 热重载),不必走 `make up`。

> 此 runbook 是各服务 Plan 的模板:Plan 4/5 新服务套脚手架后,`make up` 自动带起(在 `scripts/dev_services.sh` 加一行)、契约自动进 `make api-docs` 下拉、加各自端到端 curl 即可。
