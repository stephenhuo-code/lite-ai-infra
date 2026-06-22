# Plan 8a — metadata 数据集字段(format / num_samples / size_bytes)Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development(推荐)或 superpowers:executing-plans 逐 task 实现。步骤用 checkbox(`- [ ]`)跟踪。

**Goal:** 给 metadata 的 `Dataset` 加 3 个数据集属性字段(`format` / `num_samples` / `size_bytes`),让数据域控制台(Plan 8b)能显示数据集的格式/样本数/大小。契约先行 → metadata-service 注册时接受、读取时返回。

**Architecture:** 0.x 加法,不破现有契约。字段存进 Gravitino fileset 的 `properties`(字符串映射,整数以字符串存、读时解析回 int);`RegisterDataset` 接受这 3 个可选字段,`Dataset` 投影返回。**不含** data-pipeline 产出后自动注册(`pipelines/` 现无 register 调用,属独立增强,见"不做")。

**Tech Stack:** Python 3.12 · FastAPI · datamodel-codegen(契约生成模型)· Gravitino fileset properties · pytest(单元 FakeG + `@pytest.mark.integration` 真 Gravitino)。

**依据:** Plan 8 `design.md` §"metadata 新字段(契约任务)";ADR-016(Gravitino 租户;scope/owner 走 fileset properties)。**Plan 8b 前端依赖本 plan 的契约字段。**

---

## File Structure
**修改:**
- `contracts/openapi/metadata.yaml` — `Dataset` + `RegisterDataset` 加 3 字段。
- `libs/contracts_gen/metadata_models.py` — `make gen` 重生成(勿手改)。
- `services/metadata_service/app.py:35-41`(`_dataset` 投影)+ `:84-105`(`register` 存储)。
**测试:**
- `tests/services/metadata/test_app.py` — 加注册 round-trip + 读取 + 缺省 null 单元(FakeG)。
- `tests/integration/test_metadata_gravitino.py` — 真 Gravitino 存/取 3 字段。

---

## Task 1: 契约加 3 字段 + 重生成模型

**Files:**
- Modify: `contracts/openapi/metadata.yaml`
- Modify(生成): `libs/contracts_gen/metadata_models.py`
- Test: `tests/test_codegen.py`(既有 drift 守卫)

- [x] **Step 1: 在 `metadata.yaml` 的 `Dataset.properties` 末尾加 3 字段**

`Dataset` 现有 `properties` 末尾(`created_by` 之后)加:

```yaml
        format: {type: [string, 'null']}          # Lance / 原始 / parquet…
        num_samples: {type: [integer, 'null']}    # 样本数(行数)
        size_bytes: {type: [integer, 'null']}     # 占用字节
```

- [x] **Step 2: 在 `RegisterDataset.properties` 末尾加同样 3 字段(可选入参)**

`RegisterDataset`(现 required `[name, group_id, location]`)的 `properties` 末尾(`comment` 之后)加:

```yaml
        format: {type: [string, 'null']}
        num_samples: {type: [integer, 'null'], minimum: 0}
        size_bytes: {type: [integer, 'null'], minimum: 0}
```

- [x] **Step 3: 重生成模型**

Run: `make gen`
Expected: 无报错;`libs/contracts_gen/metadata_models.py` 的 `Dataset` 与 `RegisterDataset` 新增 `format: str | None`、`num_samples: int | None`、`size_bytes: int | None`(`conint(ge=0)` for RegisterDataset)。

- [x] **Step 4: 验证模型可导入且含新字段**

Run: `uv run python -c "from libs.contracts_gen.metadata_models import Dataset, RegisterDataset; assert 'format' in Dataset.model_fields and 'num_samples' in RegisterDataset.model_fields; print('ok')"`
Expected: 打印 `ok`。

- [x] **Step 5: 跑 codegen drift 守卫**

Run: `uv run pytest tests/test_codegen.py -q`
Expected: PASS(生成产物与契约一致)。

- [x] **Step 6: Commit**

```bash
git add contracts/openapi/metadata.yaml libs/contracts_gen/metadata_models.py
git commit -m "feat(metadata): 契约加 format/num_samples/size_bytes 字段 + 重生成 (Plan 8a)"
```

---

## Task 2: metadata-service 注册存储 + 读取返回(单元 TDD)

**Files:**
- Modify: `services/metadata_service/app.py`(`_dataset` 投影 + `register` 存储)
- Test: `tests/services/metadata/test_app.py`

- [x] **Step 1: 写失败测试(追加到 `tests/services/metadata/test_app.py` 末尾)**

```python
def test_register_persists_and_returns_three_fields():
    c = _client()
    r = c.post("/v1/catalogs/data/schemas/datasets/datasets",
               headers=_h("u-alice", ["/e-0001/g-0001/members"]),
               json={"name": "cc3m_clean", "group_id": "g-0001",
                     "location": "s3a://b/e-0001/g-0001/processed/cc3m_clean.lance",
                     "format": "Lance", "num_samples": 300, "size_bytes": 67891})
    assert r.status_code == 201
    body = r.json()
    assert body["format"] == "Lance" and body["num_samples"] == 300 and body["size_bytes"] == 67891
    # 读取也带回(类型为 int,非字符串)
    g = c.get("/v1/catalogs/data/schemas/datasets/datasets/cc3m_clean",
              headers=_h("u-alice", ["/e-0001/g-0001/members"])).json()
    assert g["num_samples"] == 300 and isinstance(g["num_samples"], int)
    assert g["size_bytes"] == 67891 and g["format"] == "Lance"

def test_register_without_three_fields_returns_null():
    c = _client()
    r = c.post("/v1/catalogs/data/schemas/datasets/datasets",
               headers=_h("u-alice", ["/e-0001/g-0001/members"]),
               json={"name": "plain_ds", "group_id": "g-0001",
                     "location": "s3a://b/e-0001/g-0001/processed/plain_ds.lance"})
    assert r.status_code == 201
    body = r.json()
    assert body["format"] is None and body["num_samples"] is None and body["size_bytes"] is None

def test_existing_dataset_projection_has_null_three_fields():
    # FakeG 预置的 cc3m(无这 3 个 property)→ 投影出 None,不报错
    c = _client()
    g = c.get("/v1/catalogs/data/schemas/datasets/datasets/cc3m",
              headers=_h("u-alice", ["/e-0001/g-0001/members"])).json()
    assert g["format"] is None and g["num_samples"] is None and g["size_bytes"] is None
```

- [x] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/services/metadata/test_app.py -q -k "three_fields or null_three"`
Expected: FAIL（响应无 `format`/`num_samples` 键,KeyError 或断言失败）。

- [x] **Step 3: 改 `_dataset` 投影(读取返回 3 字段,整数解析)**

`services/metadata_service/app.py` 的 `_dataset` 函数,在返回 dict 里追加 3 字段(整数 property 以字符串存,读时解析回 int):

```python
def _dataset(ent: str, fs: dict) -> dict:
    p, a = fs.get("properties", {}), fs.get("audit", {})
    def _int(v):
        return int(v) if v not in (None, "") else None
    return {"name": fs["name"], "enterprise_id": ent, "group_id": p.get("owner_group"),
            "owner": p.get("owner_user"), "scope": p.get("scope", "private"),
            "location": fs.get("storageLocation", ""), "comment": fs.get("comment") or None,
            "created_at": a.get("createTime"), "created_by": a.get("creator"),
            "format": p.get("format") or None,
            "num_samples": _int(p.get("num_samples")),
            "size_bytes": _int(p.get("size_bytes"))}
```

- [x] **Step 4: 改 `register` 存储(把 3 字段写进 fileset properties,整数转字符串)**

`register` handler 里构造 `properties` 处(现传 `{"owner_group", "owner_user", "scope"}`)改为:

```python
        props = {"owner_group": body.group_id, "owner_user": ctx.user, "scope": scope}
        if body.format is not None:
            props["format"] = body.format
        if body.num_samples is not None:
            props["num_samples"] = str(body.num_samples)
        if body.size_bytes is not None:
            props["size_bytes"] = str(body.size_bytes)
        try:
            fs = gravitino.create_fileset(ml, catalog, schema, body.name, body.location,
                                          comment=body.comment or "", properties=props)
```

- [x] **Step 5: 跑测试确认通过 + 既有 metadata 测试未破**

Run: `uv run pytest tests/services/metadata/test_app.py -q`
Expected: PASS（新 3 项 + 既有用例全绿;隔离/can() 用例不受影响)。

- [x] **Step 6: Commit**

```bash
git add services/metadata_service/app.py tests/services/metadata/test_app.py
git commit -m "feat(metadata): 注册存储 + 读取返回 format/num_samples/size_bytes (Plan 8a)"
```

---

## Task 3: 真 Gravitino 集成(存/取 3 字段往返)

**Files:**
- Modify: `tests/integration/test_metadata_gravitino.py`

- [x] **Step 1: 在 `test_real_gravitino_crud` 之后追加集成测试**

```python
def test_real_gravitino_three_fields_roundtrip(gravitino_url, minio_s3):
    g = GravitinoClient(base_url=gravitino_url)
    _ensure_tree(g, minio_s3)
    from services.metadata_service.app import _dataset
    n = f"it_{uuid.uuid4().hex[:6]}"
    loc = f"s3a://{_CATALOG_BUCKET}/e-0001/g-0001/processed/{n}.lance"
    g.create_fileset("e_0001", "data", "datasets", n, location=loc, comment="it",
                     properties={"owner_group": "g-0001", "owner_user": "u-alice", "scope": "private",
                                 "format": "Lance", "num_samples": "300", "size_bytes": "67891"})
    fs = g.get_fileset("e_0001", "data", "datasets", n)
    d = _dataset("e-0001", fs)
    assert d["format"] == "Lance" and d["num_samples"] == 300 and d["size_bytes"] == 67891
```

- [x] **Step 2: 起 dev 服务后跑集成测试**

Run: `make dev-up && uv run pytest tests/integration/test_metadata_gravitino.py -q -m integration`
Expected: PASS（真 Gravitino 存 properties 字符串、`_dataset` 解析回 int;Gravitino 未起则 fixture 自动 skip 而非 fail）。

- [x] **Step 3: Commit**

```bash
git add tests/integration/test_metadata_gravitino.py
git commit -m "test(metadata): 真 Gravitino 三字段存取往返集成 (Plan 8a)"
```

---

## Task 4: 全绿门禁 + 手动验收 runbook(ADR-015)

**Files:** 无新代码;跑全绿门禁 + 执行 runbook 留痕。

- [x] **Step 1: 按 CLAUDE.md 跑全绿门禁**

Run: `make gen && make lint && uv run pytest -q`
Expected: 全绿;契约无 drift(`tests/test_codegen.py`)、分层 KEPT、既有 metadata 测试不破。

- [ ] **Step 2: 手动验收 runbook(dev 真服务,人工过一遍)**

> 前置:`make dev-up`。服务起:`uv run uvicorn services.metadata_service.main:app --port 8002`(env 见 metadata main)。鉴权用 `x-test-claims`(`LITEAI_ALLOW_TEST_CLAIMS=1`)。

- [ ] **R1 带 3 字段注册**:`POST /v1/catalogs/data/schemas/datasets/datasets` body 含 `format/num_samples/size_bytes` → 201,响应回显 3 字段(num_samples/size_bytes 为整数)。
- [ ] **R2 读取返回**:`GET …/datasets/{name}` → 3 字段与注册一致、类型为 int。
- [ ] **R3 不带字段注册**:省略 3 字段 → 201,响应 3 字段为 `null`。
- [ ] **R4 既有数据集**:对一个早先注册(无 3 property)的数据集 `GET` → 3 字段 `null`,不报错。
- [ ] **R5 列表**:`GET …/datasets` 列表项也带 3 字段(本组可见,can() 过滤不受影响)。

- [ ] **Step 3: 最终 Commit(若 lint 自动修正)**

```bash
git add -A && git commit -m "chore(metadata): Plan 8a 全绿门禁 + 字段验收留痕"
```

---

## 不做(本 plan 边界)
- **data-pipeline 产出后自动注册数据集(并写入 num_samples/size_bytes)**:`pipelines/` 现无 metadata register 调用;自动注册是跨服务写 + 读 Lance count/size 的独立增强,**不在 8a**。S1 这 3 字段由"显式注册时传入"populate(ops/测试/未来管线);前端(8b)缺值优雅占位(FR-008)。何时做自动注册随数据闭环(C-1 已降级,倾向 S2a)再定。

## Self-Review
- **Spec/design 覆盖**:design §"metadata 新字段"→ Task 1(契约)+ Task 2(服务存取);FR-008(数据集展示格式/样本数/大小、缺值占位)→ 字段就位 + null 安全(Task 2 Step3 `_int` + test_existing_…null)。
- **占位符扫描**:无 TBD;每步含可运行命令 + 期望 + 完整代码。
- **类型一致性**:`_dataset` 返回键 `format/num_samples/size_bytes` 与契约 `Dataset` 字段名一致;`register` 存 `props["num_samples"]=str(...)`、`_dataset` `_int(...)` 解析回——存/取对称;`RegisterDataset.num_samples` 为 `conint(ge=0)`(yaml minimum:0),与测试值 300 一致。
