# S1 Plan 4:metadata-service(Gravitino 之上的薄 PEP,出口②)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development 或 superpowers:executing-plans 逐任务实现。步骤用 checkbox 跟踪。

**Goal:** 交付 metadata-service —— **Gravitino 之上的薄 PEP + API 优先稳定契约**。形态对齐 Gravitino 层级树(`catalogs → schemas → datasets`),但三处蓄意偏离:① **隐藏 metalake**(=企业,从 token 推导,永不可填);② **can() 过滤**(dataset 按 group);③ **fileset→Dataset 领域投影**。达成 S1 出口②"Gravitino 元数据可查"。

**Architecture(定位,owner 06-13 定稿):**
- metadata-service **不重造模型、不裸传 Gravitino、不暴露 Gravitino REST**;handler 是 Gravitino 对应接口的薄投影(list→gravitino.list、get→gravitino.get、register→gravitino.create)。
- **为什么不直接用 Gravitino REST**:Gravitino 的 `/api/metalakes/{ml}/...` 让调用者填 metalake(=企业)→ 直接暴露 = 跨租户读任意企业,绕过 §1 隔离 / §2.4 can() / ADR-011。故必须有 PEP(同我们不暴露 Keycloak Admin / OSS 给用户)。
- **三处偏离**:metalake 从 token 推(不进路径)| dataset 经 can() 按 `owner_group/scope` 过滤 | fileset 投影成 Dataset 领域对象(稳定契约,insulate Gravitino incubating 易变,spec 风险 T2)。
- **隔离层级**(ADR-016):catalog/schema 是企业级结构(metalake 已按企业隔离,**企业任意成员可列**,不按 group 过滤);**dataset(fileset)带 group 归属属性 → can() 在此过滤**。
- 分层:Gravitino client 在 `services/metadata_service/` 内(仅它调 Gravitino);依赖 libs(can/ids)。

**Tech Stack:** FastAPI、httpx、datamodel-codegen、Gravitino docker(版本 Task 1 钉)、脚手架(/docs+漂移守卫+共享鉴权)、pytest 两层。

**ADR-016 命名/映射**:enterprise_id `e-0001` →(`-`→`_`)→ metalake `e_0001`;catalog(数据源,v1 `data`=FILESET);schema(数据域);fileset=数据集,属性 `owner_group/owner_user/scope`;location `s3a://<bucket>/e-0001/g-0001/processed/<name>.lance`。**enterprise_id 直接取自调用者 ctx,不从 metalake 名反推(避歧义)。**

**v1 范围**:catalogs/schemas 导航(名字列表)+ datasets CRUD(私有 group 隔离)。`scope=shared` 读授权 = v2/Cerbos(属性记录,本计划只判 private 同组 + enterprise-admin)。自动注册(data-pipeline 挂钩)= Plan 6。Tags/lineage/policies/多 catalog 类型 = 后续。

---

### Task 1:Gravitino dev 探针(钉版本 + 实测 REST,产出 API 事实)

> 不把猜的 REST 写进后续。起真 Gravitino,跑通 metalake→FILESET catalog→schema→fileset 全链 + **list catalogs/schemas/filesets**,记录确认的端点/字段/响应包络/fileset 对象字段(含 audit/comment)/s3 bundle 依赖。

**Files:** 创建 `deploy/dev/gravitino.yml`、`spikes/gravitino_probe/probe.sh`、`spikes/gravitino_probe/RESULTS.md`

- [ ] **步骤 1:Gravitino compose**(端口避让:Gravitino server 默认 8090 撞 gateway → 宿主用 **8091**)

```yaml
# deploy/dev/gravitino.yml
services:
  gravitino:
    image: apache/gravitino:1.1.0          # 版本 Task 1 验证;不可用换最新并记 RESULTS
    ports: ["8091:8090"]                    # 宿主 8091 → 容器 8090(避让 gateway 8090)
    environment:
      GRAVITINO_MEMORY: "-Xms512m -Xmx1g"
    networks: [dev_default]                  # 与 dev MinIO 同网(容器内 minio:9000 可达)
networks:
  dev_default:
    external: true
    name: dev_default
```

- [ ] **步骤 2:探针脚本(curl 实测,含 list)**

```bash
# spikes/gravitino_probe/probe.sh
set -euo pipefail
G=${GRAVITINO_URL:-http://localhost:8091}; ML=e_0001
curl -fsS -X POST "$G/api/metalakes" -H 'Content-Type: application/json' -d '{"name":"'$ML'","comment":"e-0001"}'
curl -fsS -X POST "$G/api/metalakes/$ML/catalogs" -H 'Content-Type: application/json' -d '{
  "name":"data","type":"FILESET","comment":"datasets",
  "properties":{"location":"s3a://lite-ai-dev/","filesystem-providers":"s3",
    "s3-endpoint":"http://minio:9000","s3-access-key-id":"minio","s3-secret-access-key":"minio123"}}'
curl -fsS -X POST "$G/api/metalakes/$ML/catalogs/data/schemas" -H 'Content-Type: application/json' -d '{"name":"datasets","comment":"domain"}'
curl -fsS -X POST "$G/api/metalakes/$ML/catalogs/data/schemas/datasets/filesets" -H 'Content-Type: application/json' -d '{
  "name":"cc3m","type":"EXTERNAL","comment":"test","storageLocation":"s3a://lite-ai-dev/e-0001/g-0001/processed/cc3m.lance",
  "properties":{"owner_group":"g-0001","owner_user":"u-alice","scope":"private"}}'
echo "--- LISTS ---"
curl -fsS "$G/api/metalakes/$ML/catalogs"                                   # 列 catalog
curl -fsS "$G/api/metalakes/$ML/catalogs/data/schemas"                      # 列 schema
curl -fsS "$G/api/metalakes/$ML/catalogs/data/schemas/datasets/filesets"    # 列 fileset
curl -fsS "$G/api/metalakes/$ML/catalogs/data/schemas/datasets/filesets/cc3m"  # get(看 audit/comment 字段)
```

- [ ] **步骤 3:起依赖跑探针** `make dev-up && docker compose -f deploy/dev/gravitino.yml up -d && sleep 20 && bash spikes/gravitino_probe/probe.sh`。catalog 创建若缺 s3 bundle 失败 → 记 RESULTS,换带 bundle 镜像或挂 jar。
- [ ] **步骤 4:写 RESULTS.md** —— 记:镜像版本、各 list/get 的**响应包络键名**(`identifiers`/`names`/`catalogs`/`fileset`…)、**fileset 对象字段**(确认 `comment`、`audit.createTime`、`audit.creator`、`storageLocation`、`properties`)、s3 bundle 处理、网络接法。**后续 client 按此写。**
- [ ] **步骤 5:提交** `feat(spike): gravitino dev probe — pin REST/object shape for fileset catalog on MinIO`

---

### Task 2:`metadata.yaml` 契约 + codegen(层级 API,enrich Dataset)

**Files:** 创建 `contracts/openapi/metadata.yaml`;改 `Makefile`(gen 加 metadata)

- [ ] **步骤 1:写契约**(层级对齐 Gravitino;metalake 不进路径;Dataset enrich)

```yaml
openapi: 3.1.0
info: {title: metadata, version: 0.1.0}
paths:
  /v1/catalogs:
    get:
      summary: 列出本企业(token 推导)的 catalog
      responses:
        '200': {description: catalogs, content: {application/json: {schema: {$ref: '#/components/schemas/NameList'}}}}
        '401': {description: unauthenticated}
  /v1/catalogs/{catalog}/schemas:
    get:
      parameters: [{name: catalog, in: path, required: true, schema: {type: string}}]
      responses:
        '200': {description: schemas, content: {application/json: {schema: {$ref: '#/components/schemas/NameList'}}}}
  /v1/catalogs/{catalog}/schemas/{schema}/datasets:
    parameters:
      - {name: catalog, in: path, required: true, schema: {type: string}}
      - {name: schema, in: path, required: true, schema: {type: string}}
    get:
      summary: 列出数据集(can() 按 group 过滤)
      responses:
        '200': {description: datasets, content: {application/json: {schema: {$ref: '#/components/schemas/DatasetList'}}}}
    post:
      summary: 注册数据集
      requestBody: {required: true, content: {application/json: {schema: {$ref: '#/components/schemas/RegisterDataset'}}}}
      responses:
        '201': {description: created, content: {application/json: {schema: {$ref: '#/components/schemas/Dataset'}}}}
        '403': {description: forbidden}
  /v1/catalogs/{catalog}/schemas/{schema}/datasets/{name}:
    get:
      parameters:
        - {name: catalog, in: path, required: true, schema: {type: string}}
        - {name: schema, in: path, required: true, schema: {type: string}}
        - {name: name, in: path, required: true, schema: {type: string}}
      responses:
        '200': {description: dataset, content: {application/json: {schema: {$ref: '#/components/schemas/Dataset'}}}}
        '403': {description: forbidden}
        '404': {description: not found}
components:
  schemas:
    NameList:
      type: object
      properties: {names: {type: array, items: {type: string}}}
    Dataset:
      type: object
      required: [name, enterprise_id, group_id, scope, location]
      properties:
        name: {type: string}
        enterprise_id: {type: string, pattern: '^e-[0-9a-z]+$'}
        group_id: {type: string, pattern: '^g-[0-9a-z]+$'}
        owner: {type: [string, 'null']}
        scope: {type: string, enum: [private, shared]}
        location: {type: string}
        comment: {type: [string, 'null']}
        created_at: {type: [string, 'null']}
        created_by: {type: [string, 'null']}
    DatasetList:
      type: object
      properties: {datasets: {type: array, items: {$ref: '#/components/schemas/Dataset'}}}
    RegisterDataset:
      type: object
      required: [name, group_id, location]
      properties:
        name: {type: string, pattern: '^[a-z0-9][a-z0-9_-]{0,63}$'}
        group_id: {type: string, pattern: '^g-[0-9a-z]+$'}
        location: {type: string}
        scope: {type: string, enum: [private, shared], default: private}
        comment: {type: [string, 'null']}
```

- [ ] **步骤 2:Makefile `gen` 追加 metadata 模型**(同 identity 套路,`--output libs/contracts_gen/metadata_models.py`)
- [ ] **步骤 3:`make gen && uv run python -c "from libs.contracts_gen.metadata_models import Dataset, RegisterDataset, NameList"`** 无报错
- [ ] **步骤 4:提交** `feat(contracts): metadata.yaml — hierarchical catalogs/schemas/datasets, enriched Dataset`

---

### Task 3:Gravitino httpx 客户端(TDD;按 Task 1 确认的 REST)

**Files:** 创建 `services/metadata_service/{__init__,gravitino}.py`、`tests/services/metadata/{__init__,test_gravitino_client}.py`

> 字段/包络按 Task 1 RESULTS 写。下方用研究形态,差异按实测改。

- [ ] **步骤 1:写失败测试**(httpx.MockTransport 注入)

```python
# tests/services/metadata/test_gravitino_client.py
import json, httpx
from services.metadata_service.gravitino import GravitinoClient

def _c(handler): return GravitinoClient(base_url="http://g", transport=httpx.MockTransport(handler))

def test_list_catalogs():
    def h(req):
        assert req.url.path == "/api/metalakes/e_0001/catalogs"
        return httpx.Response(200, json={"identifiers": [{"name": "data"}, {"name": "models"}]})
    assert _c(h).list_catalogs("e_0001") == ["data", "models"]

def test_list_schemas():
    def h(req): return httpx.Response(200, json={"identifiers": [{"name": "datasets"}]})
    assert _c(h).list_schemas("e_0001", "data") == ["datasets"]

def test_list_filesets():
    def h(req): return httpx.Response(200, json={"identifiers": [{"name": "cc3m"}]})
    assert _c(h).list_filesets("e_0001", "data", "datasets") == ["cc3m"]

def test_get_fileset_exposes_props_location_audit():
    def h(req):
        return httpx.Response(200, json={"fileset": {
            "name": "cc3m", "comment": "desc", "storageLocation": "s3a://b/.../cc3m.lance",
            "properties": {"owner_group": "g-0001", "owner_user": "u-alice", "scope": "private"},
            "audit": {"creator": "svc", "createTime": "2026-06-13T00:00:00Z"}}})
    fs = _c(h).get_fileset("e_0001", "data", "datasets", "cc3m")
    assert fs["properties"]["owner_group"] == "g-0001" and fs["audit"]["creator"] == "svc"

def test_create_fileset_external_with_props():
    seen = {}
    def h(req): seen["b"] = json.loads(req.content); return httpx.Response(200, json={"fileset": {"name": "x"}})
    _c(h).create_fileset("e_0001", "data", "datasets", "x", location="s3a://b/x.lance",
                         comment="c", properties={"owner_group": "g-0001", "scope": "private"})
    assert seen["b"]["type"] == "EXTERNAL" and seen["b"]["properties"]["owner_group"] == "g-0001"
```

- [ ] **步骤 2:跑红;步骤 3:实现**(`_names` 解析包络键名按 Task 1 确认,这里设 `identifiers[].name`)

```python
# services/metadata_service/gravitino.py
from __future__ import annotations
import httpx

class GravitinoError(RuntimeError): ...

class GravitinoClient:
    """Gravitino REST 薄客户端(ADR-016 映射 + Task 1 确认端点)。transport 仅测试注入。"""
    def __init__(self, base_url: str, transport: httpx.BaseTransport | None = None):
        self._c = httpx.Client(base_url=base_url, timeout=15, transport=transport)

    def _get(self, p):
        r = self._c.get(p)
        if r.status_code >= 300: raise GravitinoError(f"{r.status_code} {r.text}")
        return r.json()

    def _post(self, p, body):
        r = self._c.post(p, json=body)
        if r.status_code >= 300: raise GravitinoError(f"{r.status_code} {r.text}")
        return r.json()

    @staticmethod
    def _names(resp) -> list[str]:
        return [i["name"] for i in resp.get("identifiers", [])]

    def list_catalogs(self, ml): return self._names(self._get(f"/api/metalakes/{ml}/catalogs"))
    def list_schemas(self, ml, cat): return self._names(self._get(f"/api/metalakes/{ml}/catalogs/{cat}/schemas"))
    def _fbase(self, ml, cat, sch): return f"/api/metalakes/{ml}/catalogs/{cat}/schemas/{sch}/filesets"
    def list_filesets(self, ml, cat, sch): return self._names(self._get(self._fbase(ml, cat, sch)))
    def get_fileset(self, ml, cat, sch, name): return self._get(f"{self._fbase(ml,cat,sch)}/{name}")["fileset"]
    def create_fileset(self, ml, cat, sch, name, location, comment="", properties=None):
        return self._post(self._fbase(ml, cat, sch), {
            "name": name, "type": "EXTERNAL", "comment": comment,
            "storageLocation": location, "properties": properties or {}})["fileset"]

    def ensure_metalake(self, ml):
        try: self._post("/api/metalakes", {"name": ml, "comment": ml})
        except GravitinoError as e:
            if "409" not in str(e) and "exist" not in str(e).lower(): raise
    # ensure_catalog(FILESET+s3 props)/ ensure_schema 同形,Task 1 确认 props 后补全
```

- [ ] **步骤 4:跑绿** → 5 passed;**步骤 5:提交** `feat(metadata): gravitino httpx client (catalogs/schemas/filesets CRUD)`

---

### Task 4:metadata-service app(TDD;层级 handler + can() + 投影)

**Files:** 创建 `services/metadata_service/{app,main}.py`、`tests/services/metadata/test_app.py`

- [ ] **步骤 1:写失败测试**(fake gravitino 注入;真 can();seam 开)

```python
# tests/services/metadata/test_app.py
import json, pytest
from fastapi.testclient import TestClient

@pytest.fixture(autouse=True)
def _seam(monkeypatch): monkeypatch.setenv("LITEAI_ALLOW_TEST_CLAIMS", "1")

class FakeG:
    def __init__(self):
        self._fs = {
            "cc3m": {"name": "cc3m", "comment": "c", "storageLocation": "s3a://b/e-0001/g-0001/processed/cc3m.lance",
                     "properties": {"owner_group": "g-0001", "owner_user": "u-alice", "scope": "private"},
                     "audit": {"creator": "u-alice", "createTime": "2026-06-13T00:00:00Z"}},
            "secret": {"name": "secret", "comment": "", "storageLocation": "s3a://b/e-0001/g-0002/processed/secret.lance",
                       "properties": {"owner_group": "g-0002", "owner_user": "u-bob", "scope": "private"},
                       "audit": {"creator": "u-bob", "createTime": "2026-06-13T00:00:00Z"}}}
    def list_catalogs(self, ml): return ["data"]
    def list_schemas(self, ml, cat): return ["datasets"]
    def list_filesets(self, ml, cat, sch): return list(self._fs)
    def get_fileset(self, ml, cat, sch, name):
        if name not in self._fs: raise KeyError(name)
        return self._fs[name]
    def create_fileset(self, ml, cat, sch, name, location, comment="", properties=None):
        self._fs[name] = {"name": name, "comment": comment, "storageLocation": location,
                          "properties": properties, "audit": {"creator": properties["owner_user"], "createTime": "t"}}
        return self._fs[name]

def _client(g=None):
    from services.metadata_service.app import build_app
    return TestClient(build_app(gravitino=g or FakeG()))

def _h(sub, groups): return {"x-test-claims": json.dumps({"sub": sub, "groups": groups})}
_ALICE = _h("u-alice", ["/e-0001/g-0001/members"])
_DS = "/v1/catalogs/data/schemas/datasets/datasets"

def test_list_catalogs_enterprise_level():
    r = _client().get("/v1/catalogs", headers=_ALICE)
    assert r.status_code == 200 and r.json()["names"] == ["data"]

def test_list_schemas():
    r = _client().get("/v1/catalogs/data/schemas", headers=_ALICE)
    assert r.status_code == 200 and r.json()["names"] == ["datasets"]

def test_list_datasets_can_filtered_to_own_group():
    r = _client().get(_DS, headers=_ALICE)
    assert [d["name"] for d in r.json()["datasets"]] == ["cc3m"]   # secret(g-0002)被过滤

def test_dataset_projection_has_audit_and_comment():
    d = _client().get(f"{_DS}/cc3m", headers=_ALICE).json()
    assert d == {"name": "cc3m", "enterprise_id": "e-0001", "group_id": "g-0001", "owner": "u-alice",
                 "scope": "private", "location": "s3a://b/e-0001/g-0001/processed/cc3m.lance",
                 "comment": "c", "created_at": "2026-06-13T00:00:00Z", "created_by": "u-alice"}

def test_get_cross_group_403():
    assert _client().get(f"{_DS}/secret", headers=_ALICE).status_code == 403

def test_get_missing_404():
    assert _client().get(f"{_DS}/nope", headers=_ALICE).status_code == 404

def test_register_own_group_201():
    g = FakeG()
    r = _client(g).post(_DS, headers=_ALICE, json={"name": "newds", "group_id": "g-0001",
                                                   "location": "s3a://b/e-0001/g-0001/processed/newds.lance"})
    assert r.status_code == 201 and "newds" in g._fs

def test_register_other_group_403():
    assert _client().post(_DS, headers=_ALICE, json={"name": "x", "group_id": "g-0002",
                                                     "location": "s3a://b/x.lance"}).status_code == 403

def test_unauth_401(monkeypatch):
    monkeypatch.delenv("LITEAI_ALLOW_TEST_CLAIMS", raising=False)
    assert _client().get("/v1/catalogs").status_code == 401

def test_docs_and_contract():
    import yaml, pathlib
    from services._scaffold.drift import assert_openapi_subset_of_contract
    c = _client()
    assert c.get("/docs").status_code == 200
    contract = yaml.safe_load(pathlib.Path("contracts/openapi/metadata.yaml").read_text())
    assert_openapi_subset_of_contract(c.app.openapi(), contract)
```

- [ ] **步骤 2:跑红;步骤 3:实现**

```python
# services/metadata_service/app.py
from __future__ import annotations
from fastapi import Depends, HTTPException
from fastapi.responses import JSONResponse

from libs.identity.context import Context
from libs.identity.ids import EnterpriseId, GroupId
from libs.authz.engine import can
from libs.authz.types import Resource
from services._scaffold.app import make_service_app
from services._scaffold.auth import context_from_request


def _metalake(ent: str) -> str: return ent.replace("-", "_")

def _enterprise(ctx: Context) -> str:
    if not ctx.memberships:
        raise HTTPException(status_code=403, detail="no enterprise membership")
    return ctx.memberships[0].enterprise_id          # v1 单企业

def _resource(ent: str, fs: dict) -> Resource:
    p = fs.get("properties", {})
    return Resource(kind="dataset", enterprise_id=EnterpriseId(ent),
                    group_id=GroupId(p["owner_group"]), scope=p.get("scope", "private"),
                    owner=p.get("owner_user"))

def _dataset(ent: str, fs: dict) -> dict:
    p, a = fs.get("properties", {}), fs.get("audit", {})
    return {"name": fs["name"], "enterprise_id": ent, "group_id": p["owner_group"],
            "owner": p.get("owner_user"), "scope": p.get("scope", "private"),
            "location": fs.get("storageLocation", ""), "comment": fs.get("comment") or None,
            "created_at": a.get("createTime"), "created_by": a.get("creator")}


def build_app(gravitino):
    app = make_service_app(title="metadata-service", version="0.1.0")

    @app.get("/v1/catalogs")
    def catalogs(ctx: Context = Depends(context_from_request)):
        return {"names": gravitino.list_catalogs(_metalake(_enterprise(ctx)))}

    @app.get("/v1/catalogs/{catalog}/schemas")
    def schemas(catalog: str, ctx: Context = Depends(context_from_request)):
        return {"names": gravitino.list_schemas(_metalake(_enterprise(ctx)), catalog)}

    @app.get("/v1/catalogs/{catalog}/schemas/{schema}/datasets")
    def list_ds(catalog: str, schema: str, ctx: Context = Depends(context_from_request)):
        ent = _enterprise(ctx); ml = _metalake(ent); out = []
        for name in gravitino.list_filesets(ml, catalog, schema):
            fs = gravitino.get_fileset(ml, catalog, schema, name)
            if can(ctx, "dataset.read", _resource(ent, fs)).allow:
                out.append(_dataset(ent, fs))
        return {"datasets": out}

    @app.get("/v1/catalogs/{catalog}/schemas/{schema}/datasets/{name}")
    def get_ds(catalog: str, schema: str, name: str, ctx: Context = Depends(context_from_request)):
        ent = _enterprise(ctx); ml = _metalake(ent)
        try:
            fs = gravitino.get_fileset(ml, catalog, schema, name)
        except Exception:
            raise HTTPException(status_code=404, detail="not found")
        d = can(ctx, "dataset.read", _resource(ent, fs))
        if not d.allow:
            return JSONResponse(status_code=403, content={"reason": d.reason})
        return _dataset(ent, fs)

    @app.post("/v1/catalogs/{catalog}/schemas/{schema}/datasets", status_code=201)
    def register(catalog: str, schema: str, body: dict, ctx: Context = Depends(context_from_request)):
        ent = _enterprise(ctx); ml = _metalake(ent)
        res = Resource(kind="dataset", enterprise_id=EnterpriseId(ent),
                       group_id=GroupId(body["group_id"]), scope=body.get("scope", "private"), owner=ctx.user)
        d = can(ctx, "dataset.register", res)
        if not d.allow:
            return JSONResponse(status_code=403, content={"reason": d.reason})
        fs = gravitino.create_fileset(ml, catalog, schema, body["name"], body["location"],
                                      comment=body.get("comment", ""),
                                      properties={"owner_group": body["group_id"], "owner_user": ctx.user,
                                                  "scope": body.get("scope", "private")})
        return _dataset(ent, fs)

    return app
```

```python
# services/metadata_service/main.py  启动:uvicorn services.metadata_service.main:app --port 8002
import os
from services.metadata_service.gravitino import GravitinoClient
from services.metadata_service.app import build_app
app = build_app(gravitino=GravitinoClient(base_url=os.environ.get("GRAVITINO_URL", "http://localhost:8091")))
```

- [ ] **步骤 4:跑绿** → 10 passed;**步骤 5:全量 + 分层 + 护栏**全绿
- [ ] **步骤 6:提交** `feat(metadata-service): hierarchical catalogs/schemas/datasets + can() + fileset→Dataset projection`

---

### Task 5:接线 —— gateway 路由 + dev 编排 + swagger + compose

**Files:** 改 `services/gateway/main.py`、`scripts/dev_services.sh`、`Makefile`(up/down 带 gravitino)

- [ ] **步骤 1:gateway 路由(单前缀覆盖整子树)** —— routes 追加 `"/v1/catalogs": os.environ.get("METADATA_URL", "http://localhost:8002")`(`/v1/catalogs/**` 全转 metadata)
- [ ] **步骤 2:dev_services.sh SERVICES 加** `"metadata|8002|services.metadata_service.main:app"`;`_env_for` 加 `metadata) echo "GRAVITINO_URL=http://localhost:8091" ;;`
- [ ] **步骤 3:`make up` 追加** `docker compose -f deploy/dev/gravitino.yml up -d`;`down` 对应 `down`
- [ ] **步骤 4:验证 swagger 聚合** `make api-docs` → 下拉含 identity-org + metadata(`swagger_urls.py` 自动发现)
- [ ] **步骤 5:提交** `feat(metadata): wire into gateway + make up + dev_services + aggregated swagger`

---

### Task 6:集成测试(真 Gravitino + MinIO)+ Lance→注册 端到端

**Files:** 创建 `tests/integration/test_metadata_gravitino.py`、`tests/integration/test_lance_register_e2e.py`;`tests/conftest.py` 加 gravitino fixture

- [ ] **步骤 1:conftest 加 `gravitino_url` fixture**(不可达则 skip,同 minio/kc 套路)
- [ ] **步骤 2:client 级集成**(真 Gravitino:ensure metalake/catalog/schema → create → list/get)

```python
# tests/integration/test_metadata_gravitino.py
import uuid, pytest
from services.metadata_service.gravitino import GravitinoClient
pytestmark = pytest.mark.integration

def test_real_gravitino_crud(gravitino_url):
    g = GravitinoClient(base_url=gravitino_url)
    g.ensure_metalake("e_0001")
    # ensure_catalog/ensure_schema(FILESET+MinIO props)— Task 1 确认后填
    n = f"it_{uuid.uuid4().hex[:6]}"
    g.create_fileset("e_0001", "data", "datasets", n, location=f"s3a://lite-ai-dev/e-0001/g-0001/processed/{n}.lance",
                     comment="it", properties={"owner_group": "g-0001", "owner_user": "u-alice", "scope": "private"})
    assert n in g.list_filesets("e_0001", "data", "datasets")
    assert g.get_fileset("e_0001", "data", "datasets", n)["properties"]["owner_group"] == "g-0001"
```

- [ ] **步骤 3:Lance→注册 端到端**(串 Plan 2/4:MinIO 建真 Lance → metadata-service 注册 → 查回 → 读回验证)

```python
# tests/integration/test_lance_register_e2e.py
import uuid, json, pytest, lance, pyarrow as pa
from fastapi.testclient import TestClient
from pipelines.data_prep.lance_writer import lance_storage_options
from services.metadata_service.gravitino import GravitinoClient
from services.metadata_service.app import build_app
pytestmark = pytest.mark.integration

def test_lance_create_then_register(minio_bucket, gravitino_url, monkeypatch):
    monkeypatch.setenv("LITEAI_ALLOW_TEST_CLAIMS", "1")
    n = f"ds_{uuid.uuid4().hex[:6]}"
    opts = lance_storage_options("http://localhost:9000", minio_bucket, "minio", "minio123", region="us-east-1")
    uri = f"s3://{minio_bucket}/e-0001/g-0001/processed/{n}.lance"      # lance 用 s3://
    lance.write_dataset(pa.table({"text": ["a", "b", "c"]}), uri, storage_options=opts, mode="overwrite")
    g = GravitinoClient(base_url=gravitino_url); g.ensure_metalake("e_0001")  # +ensure catalog/schema
    client = TestClient(build_app(gravitino=g))
    base = "/v1/catalogs/data/schemas/datasets/datasets"
    hdr = {"x-test-claims": json.dumps({"sub": "u-alice", "groups": ["/e-0001/g-0001/members"]})}
    loc = f"s3a://{minio_bucket}/e-0001/g-0001/processed/{n}.lance"     # Gravitino 记 s3a://
    assert client.post(base, headers=hdr, json={"name": n, "group_id": "g-0001", "location": loc}).status_code == 201
    assert client.get(f"{base}/{n}", headers=hdr).json()["group_id"] == "g-0001"
    assert lance.dataset(uri, storage_options=opts).count_rows() == 3   # 注册的 location 确是真 Lance
```
> **scheme 二元性**:同一物理对象,lance 读写用 `s3://`(object_store→MinIO),Gravitino fileset location 记 `s3a://`(HCFS,EXTERNAL 只记字符串)。同 bucket/key。

- [ ] **步骤 4:`make up`(含 gravitino)→ `uv run pytest -q -m integration` 全绿;步骤 5:提交** `test(metadata): real Gravitino integration + Lance→register e2e`

---

### Task 7:验收 + 合并

- [ ] **步骤 1:全量** `uv run pytest -q && uv run pytest -q -m integration && uv run lint-imports && bash scripts/ci_guards.sh && make gen && git diff --exit-code libs/contracts_gen/`
- [ ] **步骤 2:code review**(requesting-code-review,范围=本计划 commit)
- [ ] **步骤 3:push → CI 绿 → 合并 main → 删分支**
- [ ] **步骤 4:S1 spec §9.3 标 Plan 5(metadata)✅;主 spec S1 表出口② → ✅**

---

## 手动验收 runbook(宪法 §3.4)

> 前置:`make up`(含 Gravitino 8091);Keycloak realm 就绪后继续;`lite-ai-dev` bucket 需在 MinIO 建。

```bash
make up && make ps        # gateway/identity/metadata 运行中 + gravitino 容器起
make api-docs             # http://localhost:8088 下拉:identity-org + metadata 两契约

TOKEN=$(curl -fsS -d client_id=gateway -d client_secret=dev-secret -d username=alice -d password=alice \
  -d grant_type=password http://localhost:8080/realms/lite-ai/protocol/openid-connect/token \
  | uv run python -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
B=http://localhost:8090/v1/catalogs/data/schemas/datasets/datasets   # 经 gateway 8090 反代

# 1) 在 MinIO 建真 Lance 数据集
uv run python - <<'PY'
import lance, pyarrow as pa
from pipelines.data_prep.lance_writer import lance_storage_options
opts = lance_storage_options("http://localhost:9000","lite-ai-dev","minio","minio123",region="us-east-1")
lance.write_dataset(pa.table({"text":["hello","world","lite-ai"]}),
  "s3://lite-ai-dev/e-0001/g-0001/processed/cc3m.lance", storage_options=opts, mode="overwrite")
print("lance written: 3 rows")
PY

# 2) 注册 + 3) 导航查询(出口②)
curl -fsS -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' "$B" \
  -d '{"name":"cc3m","group_id":"g-0001","location":"s3a://lite-ai-dev/e-0001/g-0001/processed/cc3m.lance","comment":"CC3M 子集"}'; echo
curl -fsS -H "Authorization: Bearer $TOKEN" http://localhost:8090/v1/catalogs; echo                 # ["data"]
curl -fsS -H "Authorization: Bearer $TOKEN" http://localhost:8090/v1/catalogs/data/schemas; echo    # ["datasets"]
curl -fsS -H "Authorization: Bearer $TOKEN" "$B"; echo                                              # 列(can() 过滤)
curl -fsS -H "Authorization: Bearer $TOKEN" "$B/cc3m"; echo                                         # 单查含 comment/created_*

# 4) 直看 Gravitino 真落库
curl -fsS http://localhost:8091/api/metalakes/e_0001/catalogs/data/schemas/datasets/filesets; echo
```
**期望**:1=写 3 行;2=201;3=catalogs `["data"]` / schemas `["datasets"]` / 列出含 cc3m / 单查 group_id=g-0001 且 location 指向真 Lance、带 comment/created_at;4=Gravitino 真有该 fileset。
**收尾**:`make down`、`make api-docs-down`。

---

## 自审记录
- 定位:thin PEP + API 优先,形态对齐 Gravitino,三处蓄意偏离(隐藏 metalake / can() / 投影)—— 见 Architecture
- 占位符:Task 1 探针实测钉 REST,后续标"按 Task 1 确认";非 TBD
- 端口:Gravitino 宿主 8091 避让 gateway 8090(Task 1/5)
- 隔离:catalog/schema 企业级(成员可列);dataset 经 can() 按 group 过滤;register 跨组 deny —— 既有 can() 够用,无需改引擎;scope=shared 读=v2(声明)
- 类型一致:GravitinoClient 方法、build_app(gravitino=)、_metalake/_resource/_dataset、契约 Dataset/RegisterDataset/NameList 各处对齐
- 分层:Gravitino client 在 metadata_service 包内;依赖 libs 合法
