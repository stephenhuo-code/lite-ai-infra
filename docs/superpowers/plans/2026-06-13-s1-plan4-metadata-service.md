# S1 Plan 4:metadata-service(Gravitino 编目,出口②)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development 或 superpowers:executing-plans 逐任务实现。步骤用 checkbox 跟踪。

**Goal:** 交付 metadata-service —— 契约先行的 FastAPI 服务,经 httpx 调 Gravitino REST 注册/查询数据集(fileset),按 ADR-016 映射(enterprise=metalake、catalog=数据源、schema=数据域、group/owner/scope=fileset 属性),读写经 `can()`,套脚手架自带 /docs,达成 S1 出口②"Gravitino schema 可查"。

**Architecture:** 契约 `contracts/openapi/metadata.yaml` → datamodel-codegen 模型 → metadata-service(`services/metadata_service/`,端口 8002,套 `services/_scaffold`)→ service-internal Gravitino httpx 客户端(`services/metadata_service/gravitino.py`)。授权 = `can()`(读 fileset 的 `owner_group/scope` 属性判 group 隔离;ADR-011/016)。dev:Gravitino docker + fileset catalog 指向 **MinIO**(复用 dev compose);真 OSS 留 test/cloud。gateway 反代 `/v1/datasets` → metadata。

**Tech Stack:** FastAPI、httpx、datamodel-codegen、Gravitino docker(版本 Task 1 钉)、pytest 两层、脚手架(/docs + 漂移守卫 + 共享鉴权)。

**ADR-016 命名**:enterprise_id `e-0001` → metalake `e_0001`(连字符→下划线,Gravitino 名约束);catalog `data`(FILESET);schema `datasets`;fileset = 数据集名;属性 `owner_group=g-0001`、`owner_user`、`scope=private|shared`;location `s3a://<bucket>/e-0001/g-0001/processed/<name>.lance`。

**v1 范围**:私有(group 所有)数据集的注册/查询;`scope=shared` 属性记录但**共享读授权属 v2/Cerbos**(本计划只判 private 同组 + enterprise-admin)。自动注册(data-pipeline 产出后挂钩)= Plan 6。

---

### Task 1:Gravitino dev 探针(钉版本 + 实测 REST,产出 API 事实)

> 不把猜的 REST 写进后续任务。本任务起真 Gravitino,跑通 metalake→FILESET catalog→schema→fileset 全链,记录**确认的**端点/字段/响应包络/s3 bundle 依赖。

**Files:** 创建 `deploy/dev/gravitino.yml`、`spikes/gravitino_probe/probe.sh`、`spikes/gravitino_probe/RESULTS.md`

- [ ] **步骤 1:Gravitino compose(指向 dev MinIO)**

```yaml
# deploy/dev/gravitino.yml
services:
  gravitino:
    image: apache/gravitino:1.1.0          # 版本 Task 1 验证;不可用则换最新 tag 并记 RESULTS
    ports: ["8090:8090", "9001:9001"]       # GRAVITINO_SERVER 默认 8090 → 注意与 gateway 8090 冲突!
    # 冲突解:Gravitino 映射到宿主 8091(容器内仍 8090)
    # ports: ["8091:8090"]
    environment:
      GRAVITINO_MEMORY: "-Xms512m -Xmx1g"
```
> ⚠️ **端口冲突**:Gravitino server 默认 8090,gateway 也用 8090。本计划 Gravitino 宿主端口用 **8091**(容器内 8090),compose 写 `["8091:8090"]`。下文 GRAVITINO_URL=http://localhost:8091。

- [ ] **步骤 2:起 Gravitino,探针脚本跑通全链(对 MinIO)**

```bash
# spikes/gravitino_probe/probe.sh  —— 用 curl 实测 REST,失败即暴露真实字段名
set -euo pipefail
G=${GRAVITINO_URL:-http://localhost:8091}
ML=e_0001
# 1) metalake
curl -fsS -X POST "$G/api/metalakes" -H 'Content-Type: application/json' \
  -d '{"name":"'$ML'","comment":"enterprise e-0001"}' | tee /tmp/ml.json
# 2) FILESET catalog → MinIO(s3 兼容)
curl -fsS -X POST "$G/api/metalakes/$ML/catalogs" -H 'Content-Type: application/json' -d '{
  "name":"data","type":"FILESET","comment":"datasets",
  "properties":{"location":"s3a://lite-ai-dev/","filesystem-providers":"s3",
    "s3-endpoint":"http://minio:9000","s3-access-key-id":"minio","s3-secret-access-key":"minio123"}
}' | tee /tmp/cat.json
# 3) schema
curl -fsS -X POST "$G/api/metalakes/$ML/catalogs/data/schemas" -H 'Content-Type: application/json' \
  -d '{"name":"datasets","comment":"data domain"}' | tee /tmp/sc.json
# 4) fileset(EXTERNAL,带 owner 属性)
curl -fsS -X POST "$G/api/metalakes/$ML/catalogs/data/schemas/datasets/filesets" -H 'Content-Type: application/json' -d '{
  "name":"cc3m","type":"EXTERNAL","storageLocation":"s3a://lite-ai-dev/e-0001/g-0001/processed/cc3m.lance",
  "properties":{"owner_group":"g-0001","owner_user":"u-alice","scope":"private"}
}' | tee /tmp/fs.json
# 5) list + get
curl -fsS "$G/api/metalakes/$ML/catalogs/data/schemas/datasets/filesets" | tee /tmp/list.json
curl -fsS "$G/api/metalakes/$ML/catalogs/data/schemas/datasets/filesets/cc3m" | tee /tmp/get.json
```

- [ ] **步骤 3:起依赖跑探针**

```bash
make dev-up
docker compose -f deploy/dev/gravitino.yml up -d && sleep 20
# Gravitino 容器要能访问 minio:9000 → 需同网络;若不同 compose 网络,gravitino.yml 用 external network 接 dev_default
bash spikes/gravitino_probe/probe.sh
```
预期:5 步全 2xx。**若 catalog 创建因缺 s3 bundle 失败** → 记 RESULTS,改用带 bundle 的镜像或挂 jar(常见:`apache/gravitino:<ver>` 需额外 `gravitino-aws-bundle` jar;或先用 EXTERNAL fileset 看是否免 bundle)。

- [ ] **步骤 4:写 `RESULTS.md`** —— 记录:确认的镜像版本/端口、每步**真实**请求体字段(`storageLocation` 等)、**响应包络**(如 `{"code":0,"fileset":{...}}` / `{"code":0,"names":[...]}`)、s3 bundle 是否需要及如何加、Gravitino↔MinIO 网络接法。**后续任务的 client 按此写。**

- [ ] **步骤 5:提交** `feat(spike): gravitino dev probe — pin REST shape for fileset catalog on MinIO`

---

### Task 2:`metadata.yaml` 契约 + codegen(契约先行)

**Files:** 创建 `contracts/openapi/metadata.yaml`;修改 `Makefile`(gen 加 metadata)

- [ ] **步骤 1:写契约**(基于 ADR-016 模型)

```yaml
# contracts/openapi/metadata.yaml
openapi: 3.1.0
info: {title: metadata, version: 0.1.0}
paths:
  /v1/datasets:
    get:
      summary: 列出调用者可读的数据集(本企业,经 can() 过滤)
      responses:
        '200': {description: datasets, content: {application/json: {schema: {$ref: '#/components/schemas/DatasetList'}}}}
        '401': {description: unauthenticated}
    post:
      summary: 注册一个数据集(在调用者的企业/组下登记 fileset)
      requestBody:
        required: true
        content: {application/json: {schema: {$ref: '#/components/schemas/RegisterDataset'}}}
      responses:
        '201': {description: created, content: {application/json: {schema: {$ref: '#/components/schemas/Dataset'}}}}
        '403': {description: forbidden}
  /v1/datasets/{name}:
    get:
      summary: 取单个数据集元数据
      parameters: [{name: name, in: path, required: true, schema: {type: string}}]
      responses:
        '200': {description: dataset, content: {application/json: {schema: {$ref: '#/components/schemas/Dataset'}}}}
        '403': {description: forbidden}
        '404': {description: not found}
components:
  schemas:
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
```

> **不做 `/v1/schemas`**(owner 06-13):ADR-016 下 schema=固定数据域(v1 仅 `datasets`),列它无意义;Gravitino 结构上要求 schema,故**内部保留 `datasets`**,但不暴露列表 API。多数据域/多 catalog 出现时再加 `/v1/catalogs` 或 `/v1/schemas`(YAGNI)。

- [ ] **步骤 2:Makefile `gen` 追加 metadata 模型**

```make
gen:              ; uv run datamodel-codegen --disable-timestamp --input contracts/openapi/identity-org.yaml --input-file-type openapi --output libs/contracts_gen/identity_org_models.py && uv run datamodel-codegen --disable-timestamp --input contracts/openapi/metadata.yaml --input-file-type openapi --output libs/contracts_gen/metadata_models.py
```

- [ ] **步骤 3:生成 + 验证** `make gen && uv run python -c "from libs.contracts_gen.metadata_models import Dataset, RegisterDataset"`(无报错)
- [ ] **步骤 4:提交** `feat(contracts): metadata.yaml + codegen (datasets/schemas per ADR-016)`

---

### Task 3:Gravitino httpx 客户端(TDD;按 Task 1 确认的 REST)

**Files:** 创建 `services/metadata_service/__init__.py`、`services/metadata_service/gravitino.py`、`tests/services/metadata/__init__.py`、`tests/services/metadata/test_gravitino_client.py`

> 客户端方法 + 响应解析按 **Task 1 RESULTS.md 确认的字段/包络**写。下方代码用研究得到的文档形态,Task 1 若发现差异(如包络键名)按实测改。

- [ ] **步骤 1:写失败测试**(用 httpx.MockTransport 注入,不依赖真 Gravitino)

```python
# tests/services/metadata/test_gravitino_client.py
import httpx
from services.metadata_service.gravitino import GravitinoClient

def _client(handler):
    return GravitinoClient(base_url="http://g", transport=httpx.MockTransport(handler))

def test_list_filesets_parses_envelope():
    def h(req):
        assert req.url.path == "/api/metalakes/e_0001/catalogs/data/schemas/datasets/filesets"
        return httpx.Response(200, json={"code": 0, "names": ["cc3m", "coco"]})
    assert _client(h).list_filesets("e_0001", "data", "datasets") == ["cc3m", "coco"]

def test_get_fileset_returns_props_and_location():
    def h(req):
        return httpx.Response(200, json={"code": 0, "fileset": {
            "name": "cc3m", "storageLocation": "s3a://b/e-0001/g-0001/processed/cc3m.lance",
            "properties": {"owner_group": "g-0001", "owner_user": "u-alice", "scope": "private"}}})
    fs = _client(h).get_fileset("e_0001", "data", "datasets", "cc3m")
    assert fs["properties"]["owner_group"] == "g-0001"
    assert fs["storageLocation"].endswith("cc3m.lance")

def test_create_fileset_posts_external_with_props():
    seen = {}
    def h(req):
        import json
        seen["body"] = json.loads(req.content); return httpx.Response(200, json={"code": 0, "fileset": {"name": "x"}})
    _client(h).create_fileset("e_0001", "data", "datasets", "x",
                              location="s3a://b/e-0001/g-0001/processed/x.lance",
                              properties={"owner_group": "g-0001", "scope": "private"})
    assert seen["body"]["type"] == "EXTERNAL"
    assert seen["body"]["properties"]["owner_group"] == "g-0001"
```

- [ ] **步骤 2:跑红;步骤 3:实现**(注:`transport` seam 同 proxy 套路)

```python
# services/metadata_service/gravitino.py
from __future__ import annotations
import httpx

class GravitinoError(RuntimeError): ...

class GravitinoClient:
    """Gravitino REST 薄客户端(按 ADR-016 映射 + Task 1 确认的端点)。
    transport 仅测试注入;生产用真 httpx 默认。"""
    def __init__(self, base_url: str, transport: httpx.BaseTransport | None = None):
        self._c = httpx.Client(base_url=base_url, timeout=15,
                               transport=transport)

    def _post(self, path: str, body: dict) -> dict:
        r = self._c.post(path, json=body)
        if r.status_code >= 300:
            raise GravitinoError(f"{r.status_code} {r.text}")
        return r.json()

    def _get(self, path: str) -> dict:
        r = self._c.get(path)
        if r.status_code >= 300:
            raise GravitinoError(f"{r.status_code} {r.text}")
        return r.json()

    def _base(self, ml, cat, sch):
        return f"/api/metalakes/{ml}/catalogs/{cat}/schemas/{sch}/filesets"

    def list_filesets(self, ml: str, cat: str, sch: str) -> list[str]:
        return self._get(self._base(ml, cat, sch)).get("names", [])

    def get_fileset(self, ml: str, cat: str, sch: str, name: str) -> dict:
        return self._get(f"{self._base(ml, cat, sch)}/{name}")["fileset"]

    def create_fileset(self, ml, cat, sch, name, location, properties) -> dict:
        return self._post(self._base(ml, cat, sch), {
            "name": name, "type": "EXTERNAL", "storageLocation": location,
            "properties": properties})["fileset"]

    # ensure_* 幂等(409/已存在视为 OK)—— 供集成/启动期建骨架
    def ensure_metalake(self, ml: str) -> None:
        try: self._post("/api/metalakes", {"name": ml, "comment": ml})
        except GravitinoError as e:
            if "409" not in str(e) and "exists" not in str(e).lower(): raise
    # ensure_catalog / ensure_schema 同形(Task 1 确认 props 后补全;含 FILESET+s3 props)
```

- [ ] **步骤 4:跑绿** → 3 passed;**步骤 5:提交** `feat(metadata): gravitino httpx client (fileset CRUD per probe)`

---

### Task 4:metadata-service app + can() 授权(TDD,套脚手架)

**Files:** 创建 `services/metadata_service/app.py`、`services/metadata_service/main.py`、`tests/services/metadata/test_app.py`

- [ ] **步骤 1:写失败测试**(Gravitino client 用 fake 注入;授权走真 `can()`;seam 开)

```python
# tests/services/metadata/test_app.py
import json, pytest
from fastapi.testclient import TestClient

@pytest.fixture(autouse=True)
def _seam(monkeypatch): monkeypatch.setenv("LITEAI_ALLOW_TEST_CLAIMS", "1")

class FakeGravitino:
    def __init__(self): self.filesets = {
        "cc3m": {"name": "cc3m", "storageLocation": "s3a://b/e-0001/g-0001/processed/cc3m.lance",
                 "properties": {"owner_group": "g-0001", "owner_user": "u-alice", "scope": "private"}},
        "secret": {"name": "secret", "storageLocation": "s3a://b/e-0001/g-0002/processed/secret.lance",
                   "properties": {"owner_group": "g-0002", "owner_user": "u-bob", "scope": "private"}}}
    def list_filesets(self, ml, cat, sch): return list(self.filesets)
    def get_fileset(self, ml, cat, sch, name): return self.filesets[name]
    def create_fileset(self, ml, cat, sch, name, location, properties):
        self.filesets[name] = {"name": name, "storageLocation": location, "properties": properties}
        return self.filesets[name]

def _client(g=None):
    from services.metadata_service.app import build_app
    return TestClient(build_app(gravitino=g or FakeGravitino()))

def _hdr(sub, groups): return {"x-test-claims": json.dumps({"sub": sub, "groups": groups})}

def test_list_filters_by_can_same_group_only():
    # alice 属 g-0001 → 只应看到 cc3m(g-0001),看不到 secret(g-0002)
    r = _client().get("/v1/datasets", headers=_hdr("u-alice", ["/e-0001/g-0001/members"]))
    assert r.status_code == 200
    names = [d["name"] for d in r.json()["datasets"]]
    assert names == ["cc3m"]

def test_get_cross_group_denied_403():
    r = _client().get("/v1/datasets/secret", headers=_hdr("u-alice", ["/e-0001/g-0001/members"]))
    assert r.status_code == 403

def test_get_own_dataset_ok():
    r = _client().get("/v1/datasets/cc3m", headers=_hdr("u-alice", ["/e-0001/g-0001/members"]))
    assert r.status_code == 200 and r.json()["group_id"] == "g-0001"

def test_register_in_own_group_creates():
    g = FakeGravitino()
    r = _client(g).post("/v1/datasets", headers=_hdr("u-alice", ["/e-0001/g-0001/members"]),
                        json={"name": "newds", "group_id": "g-0001",
                              "location": "s3a://b/e-0001/g-0001/processed/newds.lance"})
    assert r.status_code == 201 and "newds" in g.filesets

def test_register_other_group_denied_403():
    r = _client().post("/v1/datasets", headers=_hdr("u-alice", ["/e-0001/g-0001/members"]),
                       json={"name": "x", "group_id": "g-0002", "location": "s3a://b/.../x.lance"})
    assert r.status_code == 403

def test_unauthenticated_401(monkeypatch):
    monkeypatch.delenv("LITEAI_ALLOW_TEST_CLAIMS", raising=False)
    assert _client().get("/v1/datasets").status_code == 401

def test_docs_and_contract():
    import yaml, pathlib
    from services._scaffold.drift import assert_openapi_subset_of_contract
    c = _client()
    assert c.get("/docs").status_code == 200
    contract = yaml.safe_load(pathlib.Path("contracts/openapi/metadata.yaml").read_text())
    assert_openapi_subset_of_contract(c.app.openapi(), contract)
```

- [ ] **步骤 2:跑红;步骤 3:实现**(metalake = enterprise_id 下划线化;Resource 从 fileset 属性构建;can() 判)

```python
# services/metadata_service/app.py
from __future__ import annotations
from fastapi import Depends, Request, HTTPException
from fastapi.responses import JSONResponse

from libs.identity.context import Context
from libs.identity.ids import EnterpriseId, GroupId
from libs.authz.engine import can
from libs.authz.types import Resource
from services._scaffold.app import make_service_app
from services._scaffold.auth import context_from_request

_CATALOG, _SCHEMA = "data", "datasets"

def _metalake(enterprise_id: str) -> str:
    return enterprise_id.replace("-", "_")          # e-0001 → e_0001(Gravitino 名约束)

def _fileset_to_resource(enterprise_id: str, fs: dict) -> Resource:
    p = fs.get("properties", {})
    return Resource(kind="dataset", enterprise_id=EnterpriseId(enterprise_id),
                    group_id=GroupId(p["owner_group"]), scope=p.get("scope", "private"),
                    owner=p.get("owner_user"))

def _to_dataset(enterprise_id: str, fs: dict) -> dict:
    p = fs.get("properties", {})
    return {"name": fs["name"], "enterprise_id": enterprise_id, "group_id": p["owner_group"],
            "owner": p.get("owner_user"), "scope": p.get("scope", "private"),
            "location": fs.get("storageLocation", "")}

def _caller_enterprise(ctx: Context) -> str:
    if not ctx.memberships:
        raise HTTPException(status_code=403, detail="no enterprise membership")
    return ctx.memberships[0].enterprise_id          # v1 单企业;多企业时按请求 scope 选

def build_app(gravitino):
    app = make_service_app(title="metadata-service", version="0.1.0")

    @app.get("/v1/datasets")
    def list_datasets(ctx: Context = Depends(context_from_request)):
        ent = _caller_enterprise(ctx); ml = _metalake(ent)
        out = []
        for name in gravitino.list_filesets(ml, _CATALOG, _SCHEMA):
            fs = gravitino.get_fileset(ml, _CATALOG, _SCHEMA, name)
            res = _fileset_to_resource(ent, fs)
            if can(ctx, "dataset.read", res).allow:
                out.append(_to_dataset(ent, fs))
        return {"datasets": out}

    @app.get("/v1/datasets/{name}")
    def get_dataset(name: str, ctx: Context = Depends(context_from_request)):
        ent = _caller_enterprise(ctx); ml = _metalake(ent)
        try:
            fs = gravitino.get_fileset(ml, _CATALOG, _SCHEMA, name)
        except Exception:
            raise HTTPException(status_code=404, detail="not found")
        d = can(ctx, "dataset.read", _fileset_to_resource(ent, fs))
        if not d.allow:
            return JSONResponse(status_code=403, content={"reason": d.reason})
        return _to_dataset(ent, fs)

    @app.post("/v1/datasets", status_code=201)
    def register(body: dict, ctx: Context = Depends(context_from_request)):
        ent = _caller_enterprise(ctx); ml = _metalake(ent)
        res = Resource(kind="dataset", enterprise_id=EnterpriseId(ent),
                       group_id=GroupId(body["group_id"]), scope=body.get("scope", "private"),
                       owner=ctx.user)
        d = can(ctx, "dataset.register", res)
        if not d.allow:
            return JSONResponse(status_code=403, content={"reason": d.reason})
        fs = gravitino.create_fileset(ml, _CATALOG, _SCHEMA, body["name"], body["location"],
                                      {"owner_group": body["group_id"], "owner_user": ctx.user,
                                       "scope": body.get("scope", "private")})
        return _to_dataset(ent, fs)

    return app
```

```python
# services/metadata_service/main.py  启动:uvicorn services.metadata_service.main:app --port 8002
import os
from services.metadata_service.gravitino import GravitinoClient
from services.metadata_service.app import build_app
app = build_app(gravitino=GravitinoClient(base_url=os.environ.get("GRAVITINO_URL", "http://localhost:8091")))
```

- [ ] **步骤 4:跑绿** → 7 passed(注:`dataset.register` 不是 mutation 后缀,can() 对本组 member 放行;跨组 role=None→deny ✓);**步骤 5:全量 + 分层 + 护栏**
- [ ] **步骤 6:提交** `feat(metadata-service): datasets/schemas API with can() authz over fileset attrs`

---

### Task 5:接线 —— gateway 路由 + dev 编排 + swagger + compose

**Files:** 修改 `services/gateway/main.py`、`scripts/dev_services.sh`、`Makefile`(up 带 gravitino)、`deploy/dev/swagger-ui.yml`(无需改,URLS 自动发现)

- [ ] **步骤 1:gateway 路由表加 metadata**

```python
# services/gateway/main.py 的 routes 追加
    "/v1/datasets": os.environ.get("METADATA_URL", "http://localhost:8002"),
```

- [ ] **步骤 2:dev_services.sh SERVICES 加一行 + env**

```bash
  "metadata|8002|services.metadata_service.main:app"
# _env_for() 加:metadata) echo "GRAVITINO_URL=http://localhost:8091" ;;
```

- [ ] **步骤 3:`make up` 同时起 Gravitino** —— `up` 目标追加 `docker compose -f deploy/dev/gravitino.yml up -d`;`down` 对应 `down`。

- [ ] **步骤 4:验证 swagger 聚合** `make api-docs` → http://localhost:8088 下拉应有 **identity-org + metadata** 两项(`swagger_urls.py` 自动发现,无需改)。
- [ ] **步骤 5:提交** `feat(metadata): wire into gateway routes + make up + dev_services + aggregated swagger`

---

### Task 6:集成测试(真 Gravitino + MinIO)+ 漂移守卫

**Files:** 创建 `tests/integration/test_metadata_gravitino.py`;`tests/conftest.py` 加 gravitino fixture

- [ ] **步骤 1:conftest 加 gravitino reachable fixture**(同 minio/kc 套路:不可达则 skip)
- [ ] **步骤 2:集成测试**(真 Gravitino:ensure metalake/catalog/schema → register → list/get;经真 GravitinoClient)

```python
# tests/integration/test_metadata_gravitino.py
import os, uuid, pytest
from services.metadata_service.gravitino import GravitinoClient
pytestmark = pytest.mark.integration

def test_register_and_read_back_real_gravitino(gravitino_url):
    g = GravitinoClient(base_url=gravitino_url)
    g.ensure_metalake("e_0001")
    # ensure_catalog/ensure_schema(FILESET+MinIO props)— Task 1 确认 props 后填
    name = f"it_{uuid.uuid4().hex[:6]}"
    g.create_fileset("e_0001", "data", "datasets", name,
                     location=f"s3a://lite-ai-dev/e-0001/g-0001/processed/{name}.lance",
                     properties={"owner_group": "g-0001", "owner_user": "u-alice", "scope": "private"})
    assert name in g.list_filesets("e_0001", "data", "datasets")
    fs = g.get_fileset("e_0001", "data", "datasets", name)
    assert fs["properties"]["owner_group"] == "g-0001"
```

- [ ] **步骤 3:端到端场景测试 —— Lance 建真数据集 → 经 metadata-service 注册 → 查回 + 验证 location 指向真 Lance**(集成,串起 Plan 2 与 Plan 4)

```python
# tests/integration/test_lance_register_e2e.py
import os, uuid, json
import lance, pyarrow as pa, pytest
from fastapi.testclient import TestClient
from pipelines.data_prep.lance_writer import lance_storage_options
from services.metadata_service.gravitino import GravitinoClient
from services.metadata_service.app import build_app
pytestmark = pytest.mark.integration

def test_create_lance_then_register_and_read_back(minio_bucket, gravitino_url, monkeypatch):
    monkeypatch.setenv("LITEAI_ALLOW_TEST_CLAIMS", "1")
    name = f"ds_{uuid.uuid4().hex[:6]}"
    # 1) 在 MinIO 上建一个真 Lance 数据集(lance 用 s3:// scheme)
    ep = "http://localhost:9000"
    opts = lance_storage_options(ep, minio_bucket, "minio", "minio123", region="us-east-1")
    uri_s3 = f"s3://{minio_bucket}/e-0001/g-0001/processed/{name}.lance"
    lance.write_dataset(pa.table({"text": ["a", "b", "c"]}), uri_s3, storage_options=opts, mode="overwrite")
    # 2) 经 metadata-service 注册(Gravitino 记 s3a:// 同一物理路径;EXTERNAL fileset)
    g = GravitinoClient(base_url=gravitino_url)
    g.ensure_metalake("e_0001")  # ensure_catalog/schema 见 Task 3(FILESET+MinIO props)
    client = TestClient(build_app(gravitino=g))
    loc_s3a = f"s3a://{minio_bucket}/e-0001/g-0001/processed/{name}.lance"
    r = client.post("/v1/datasets",
                    headers={"x-test-claims": json.dumps({"sub": "u-alice", "groups": ["/e-0001/g-0001/members"]})},
                    json={"name": name, "group_id": "g-0001", "location": loc_s3a})
    assert r.status_code == 201 and r.json()["location"] == loc_s3a
    # 3) 查回
    got = client.get(f"/v1/datasets/{name}",
                     headers={"x-test-claims": json.dumps({"sub": "u-alice", "groups": ["/e-0001/g-0001/members"]})})
    assert got.status_code == 200 and got.json()["group_id"] == "g-0001"
    # 4) 验证注册的 location 确实是真 Lance(用 s3:// 等价路径读回)
    ds = lance.dataset(uri_s3, storage_options=opts)
    assert ds.count_rows() == 3
```
> **scheme 二元性**(实现要点):同一物理对象,**lance 读写用 `s3://`**(object_store→MinIO),**Gravitino fileset location 记 `s3a://`**(HCFS,EXTERNAL 只记字符串不读)。同 bucket/key,仅 scheme 不同。

- [ ] **步骤 4:跑** `make up`(含 gravitino)→ `uv run pytest -q -m integration` 全绿(既有 + 新 client 测 + Lance 端到端)
- [ ] **步骤 5:提交** `test(metadata): real Gravitino integration + Lance-create→register e2e`

---

### Task 7:验收 + 合并

- [ ] **步骤 1:全量** `uv run pytest -q && uv run pytest -q -m integration && uv run lint-imports && bash scripts/ci_guards.sh && make gen && git diff --exit-code libs/contracts_gen/`
- [ ] **步骤 2:code review**(superpowers:requesting-code-review,范围 = 本计划 commit)
- [ ] **步骤 3:push → CI 绿 → 合并 main → 删分支**
- [ ] **步骤 4:S1 spec §9.3 标 Plan 5(metadata)✅;主 spec S1 表出口② → ✅**

---

## 手动验收 runbook(宪法 §3.4 必含)

> 前置:`make up`(现已含 Gravitino 8091)。Keycloak realm 就绪后继续。

```bash
make up && make ps        # gateway/identity/metadata 都运行中 + gravitino 容器起

# 1) 聚合 Swagger:一个页面看 identity-org + metadata 两个契约
make api-docs             # → http://localhost:8088 顶部下拉两项

# 2) 拿 token
TOKEN=$(curl -fsS -d client_id=gateway -d client_secret=dev-secret -d username=alice -d password=alice \
  -d grant_type=password http://localhost:8080/realms/lite-ai/protocol/openid-connect/token \
  | uv run python -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

# 3) 先在 Lance 建一个真测试数据集(写进 MinIO 的隔离路径;lance 用 s3://)
uv run python - <<'PY'
import lance, pyarrow as pa
from pipelines.data_prep.lance_writer import lance_storage_options
opts = lance_storage_options("http://localhost:9000", "lite-ai-dev", "minio", "minio123", region="us-east-1")
lance.write_dataset(pa.table({"text": ["hello", "world", "lite-ai"]}),
                    "s3://lite-ai-dev/e-0001/g-0001/processed/cc3m.lance",
                    storage_options=opts, mode="overwrite")
print("lance dataset written: 3 rows")
PY
# (注:lite-ai-dev bucket 需先在 MinIO 建;make up 后 `aws --endpoint http://localhost:9000 s3 mb` 或 mc)

# 4) 经 gateway 反代注册到 Gravitino(location 记 s3a:// 同一物理路径)
curl -fsS -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  http://localhost:8090/v1/datasets \
  -d '{"name":"cc3m","group_id":"g-0001","location":"s3a://lite-ai-dev/e-0001/g-0001/processed/cc3m.lance"}'; echo

# 5) 查询(出口② 核心:数据集可查)
curl -fsS -H "Authorization: Bearer $TOKEN" http://localhost:8090/v1/datasets; echo      # 列出(can() 过滤)
curl -fsS -H "Authorization: Bearer $TOKEN" http://localhost:8090/v1/datasets/cc3m; echo # 单查 → location 指向上面的真 Lance

# 6) 直接看 Gravitino 里的 fileset(证明真落库)
curl -fsS http://localhost:8091/api/metalakes/e_0001/catalogs/data/schemas/datasets/filesets; echo
```
**期望**:3=写入 3 行;4=201 + 返回 dataset;5=列出含 cc3m / 单查 group_id=g-0001 且 location 指向真 Lance;6=Gravitino 真有该 fileset。
**收尾**:`make down`(含停 gravitino)、`make api-docs-down`。

> Plan 5/6 的 runbook 复用此结构。

## 自审记录
- 占位符:Task 1 是探针(实测钉死 REST),后续 client/集成的 Gravitino 字段标注"按 Task 1 确认";非 TBD
- 端口冲突:Gravitino 默认 8090 撞 gateway → 本计划 Gravitino 宿主用 **8091**(Task 1 步骤 1 已写明)
- 类型一致:`GravitinoClient`/`build_app(gravitino=)`/`_metalake`/`Resource(kind=dataset)` 各处签名对齐;契约模型名 Dataset/RegisterDataset 与 codegen 一致
- 授权:dataset.read 私有同组放行、跨组/跨企业 deny(既有 can() 够用,无需改引擎);scope=shared 读 = v2(已声明)
- 分层:Gravitino client 在 metadata_service 包内(仅它调 Gravitino);依赖 libs(can/ids)合法
