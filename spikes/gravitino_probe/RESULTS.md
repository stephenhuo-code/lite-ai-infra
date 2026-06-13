# Gravitino dev 探针 — 实测结果(钉 REST/对象形态)

> 跑法:`make dev-up && docker compose -f deploy/dev/gravitino.yml up -d && sleep 20 && bash spikes/gravitino_probe/probe.sh`
> 本文件是 Task 3(client)/Task 6(集成)字段与解析的**唯一真相源**。计划里的 REST 是文档推测,以下为实测;不符处以实测为准。

## 镜像 / 版本

- `apache/gravitino:1.1.0`(`/api/version`:version 1.1.0,compileDate 16/12/2025,gitCommit 5a6b5ae)。
- **S3 bundle 已内置**:FILESET catalog + `filesystem-providers=s3` 直接可用,**无需额外挂 jar / 换镜像**。
- 端口:容器内 8090 → 宿主 **8091**(避让 gateway 8090)。
- 网络:`dev_default`(external);Gravitino 容器内可达 `http://minio:9000`(health 200)。
- 认证:dev 无鉴权,`audit.creator = "anonymous"`(metadata-service 在其之上做 PEP,Gravitino 本身不认人)。

## 端点(全部 `/api/metalakes/{ml}/...`,与计划一致)

| 动作 | 方法 路径 | HTTP |
|---|---|---|
| create metalake | POST `/api/metalakes` | 200 |
| list metalakes | GET `/api/metalakes` | 200 |
| drop metalake | DELETE `/api/metalakes/{ml}?force=true` | 200 |
| create catalog | POST `/api/metalakes/{ml}/catalogs` | 200 |
| list catalogs | GET `/api/metalakes/{ml}/catalogs` | 200 |
| create schema | POST `/api/metalakes/{ml}/catalogs/{cat}/schemas` | 200 |
| list schemas | GET `/api/metalakes/{ml}/catalogs/{cat}/schemas` | 200 |
| create fileset | POST `.../schemas/{sch}/filesets` | 200(**非 201**) |
| list filesets | GET `.../schemas/{sch}/filesets` | 200 |
| get fileset | GET `.../schemas/{sch}/filesets/{name}` | 200 |

## 响应包络键名(client `_get`/`_post`/`_names` 按此)

- **list**(catalogs/schemas/filesets):`{"code":0,"identifiers":[{"namespace":[...],"name":"X"}]}`
  → 列表键 = **`identifiers`**,名字 = 每项 **`name`**。(计划 `_names = [i["name"] for i in resp["identifiers"]]` ✓ 正确)
- **get fileset**:`{"code":0,"fileset":{...}}` → 取 **`fileset`** ✓
- **create fileset**:`{"code":0,"fileset":{...}}` → 取 **`fileset`** ✓(HTTP 200)
- create metalake/catalog/schema:`{"code":0,"metalake|catalog|schema":{...}}`
- list metalakes:`{"code":0,"metalakes":[...]}`

## fileset 对象字段(实测 get/create 完整形态)

```json
{
  "name": "cc3m",
  "comment": "probe",
  "type": "external",
  "storageLocation": "s3a://lite-ai-dev/e-0001/g-0001/processed/cc3m.lance",
  "storageLocations": {"unknown": "s3a://lite-ai-dev/e-0001/g-0001/processed/cc3m.lance"},
  "properties": {
    "scope": "private",
    "owner_group": "g-0001",
    "owner_user": "u-alice",
    "default-location-name": "unknown"
  },
  "audit": {"creator": "anonymous", "createTime": "2026-06-13T21:05:08.684292586Z"}
}
```

确认用于 `_dataset` 投影 / `_resource`:
- `storageLocation`(camelCase,单值)→ Dataset.location ✓
- `comment` ✓(可空)
- `properties.owner_group` / `owner_user` / `scope` ✓(自定义属性原样回显)
- `audit.createTime` → created_at;`audit.creator` → created_by ✓
- **注意**:get fileset 的 `audit` 只有 `creator`+`createTime`,**无** `lastModifier`/`lastModifiedTime`(catalog/schema 的 audit 才有)。投影只读这两个,安全。
- Gravitino 自动注入 `storageLocations`(map)、`properties.default-location-name=unknown`、`type` 小写化(`EXTERNAL`→`external`)。投影忽略这些多余字段。

## 错误包络 / 状态码(404/409/500 行为)

`{"code":<int>,"type":"NoSuchXException|...","message":"...","stack":[...]}`

| 场景 | HTTP | code | type |
|---|---|---|---|
| get 不存在的 fileset | **404** | 1003 | NoSuchFilesetException |
| list 不存在的 schema 下 filesets | 404 | 1003 | NoSuchSchemaException |
| list 不存在 metalake 的 catalogs | 404 | 1003 | NoSuchMetalakeException |
| create 已存在 fileset | **409** | — | (AlreadyExists) |
| create 已存在 metalake | 409 | 1004 | MetalakeAlreadyExistsException |
| schema 位置校验失败(S3 不可达) | 500 | 1002 | RuntimeException |

→ client `_get`/`_post` 对 `status >= 300` 抛 `GravitinoError`(含 status+text);app 的 `get_ds` catch → 404,`ensure_metalake` 容忍 409。✓ 计划逻辑成立。

## ⚠️ 关键偏离(计划未覆盖,Task 3/6 必须照做)

**FILESET catalog 在 `create schema` 时会对 schema 推导位置(`<catalog.location>/<schema>`,如 `s3a://lite-ai-dev/datasets`)做真实 S3 `getFileStatus` 校验。** 因此:

1. **bucket 必须先存在**:`lite-ai-dev` 不存在时校验失败。集成测试/runbook 要先建桶(MinIO `create_bucket`)。
2. **必须强制 path-style 寻址**:S3A 默认 virtual-host(`lite-ai-dev.minio:9000`),MinIO 单端点不应答 → `NoHttpResponseException: target server failed to respond`(连上但无 HTTP 响应,非 DNS 错)。
   catalog 创建属性需加:
   ```json
   "s3-path-style-access": "true",
   "gravitino.bypass.fs.s3a.path.style.access": "true"
   ```
   (两者都加;`gravitino.bypass.<hadoop-key>` 是 Gravitino 透传 Hadoop conf 的机制,确保 S3A 拿到 path-style。)

→ **Task 3 `ensure_catalog`**:FILESET + 上述 5 个 S3 属性(endpoint/ak/sk/providers + path-style ×2)+ `location=s3a://<bucket>/`。
→ **Task 6 集成 fixture**:先 `minio_s3.create_bucket("lite-ai-dev")`(或用现有桶)再 ensure catalog/schema。

## 已验证的最小成功链(clean state)

```
drop metalake e_0001 force → create metalake → create catalog(FILESET+path-style)
→ create schema datasets → create fileset cc3m(EXTERNAL+props)
→ list catalogs=[data] / list schemas=[datasets] / list filesets=[cc3m] / get cc3m ✓
```
全链 200,字段如上。
