# ADR-016: Gravitino 租户/资源映射 — enterprise=metalake,group=资源属性(非 schema)

- 状态：Accepted（2026-06-13，owner)
- 决策人：owner
- 相关：ADR-010(两级租户模型)、ADR-011(授权 = Cerbos/can(),非数据源内置 RBAC);constitution §1(标识/隔离)/ §1.5(归属编码在资源)/ §1.6(硬隔离);S1 设计 spec §9(metadata-service);Gravitino 1.1.0

---

## Context

metadata-service(S1,出口②)用 Gravitino 编目数据集。需定 ADR-010 两级模型(enterprise_id / group_id)如何映射到 Gravitino 层级(Metalake → Catalog → Schema → Fileset/Table)。

关键认识(owner 厘清):**Gravitino 的 catalog/schema 是"数据组织"维度,不是"租户/权限"维度**——catalog = 一个数据源(PG 库 / Hive / 一个 fileset 存储),schema = 该源内的命名空间(PG schema / fileset 逻辑分区)。把 group 塞进 schema 名是弯曲该语义;group 是**身份/访问**概念,应走资源属性 + 授权决策。宪法 §1.5"归属编码在资源自身"指 **fileset 的 properties / OSS 路径**,并不要求编码进 namespace。

授权权威层是 `can()`/Cerbos(ADR-011),**不是** Gravitino 内置 RBAC。

## Decision

**两个维度分开:**

| 维度 | 性质 | 映射 |
|---|---|---|
| **enterprise** | 硬隔离边界(§1.6,跨企业是硬墙) | **= Metalake**(`e_0001`);结构性硬隔离;跨 metalake = 跨企业 |
| **数据组织** | 数据源 / 命名空间 | **Catalog** = 数据源(`data` 类型 FILESET→OSS;将来 `models` 等,企业内可多个);**Schema** = 数据域(v1 用 `datasets`),**不是 group** |
| **group / owner / scope** | 访问维度(身份) | **Fileset properties**(`owner_group`、`owner_user`、`scope=private\|shared`)+ OSS 物理路径 `e-XXXX/g-YYYY/...` |

**三属性的语义角色(2026-06-13 澄清,owner 决策"保留 group、不拆地基"):**
- `owner_user` = **owner 真相源**(谁创建/拥有;owner 专属删改权,engine 已判)
- `owner_group` = **默认 grantee / 隔离单元**(宪法 §1.2 私有资源归属单元;同组默认可见)
- `scope` = **共享开关**(private | shared=企业级)
- **v2 演进**(见 ADR-011 升级路径):per-user / per-resource grant 作 **group 之上的叠加层**(Cerbos 派生角色),**不拆 group**;v1 不交付细粒度 grant。

```
Metalake: e_0001                          ← 企业(硬边界)
└─ Catalog: data (FILESET, S3→OSS/MinIO)  ← 数据源(企业内可多个: data/models/…)
   └─ Schema: datasets                    ← 数据域命名空间(非 group)
      └─ Fileset: cc3m
           properties: owner_group=g-0001, owner_user=u-alice, scope=private
           location:   s3a://<bucket>/e-0001/g-0001/processed/cc3m.lance
```

**访问判定**:metadata-service 读 fileset 的 `owner_group`/`scope` → 交 `can()`(调用者 group 匹配 / `scope=shared` / enterprise-admin / platform-admin 走特权 API)。**group 隔离由 can() 按资源属性计算,非 namespace 隔离。**

**与 Gravitino RBAC 的关系**:Gravitino 自带 RBAC(securable object 在 metalake/catalog/schema 级)**不作 v1 权威 PEP**;权威是 `can()`(ADR-011)。Gravitino RBAC 可留作 v2 纵深防御。

## Consequences

### 正面
- enterprise(硬墙)结构化、group(可共享软边界)属性化 —— 与宪法两级模型的硬/软性质对应。
- 不弯曲 Gravitino catalog/schema 语义;将来接 relational catalog(真 PG)时 schema 即 PG schema,无冲突。
- 企业内可挂多个 catalog(data/models/…),catalog 名干净(无 `e_xxxx_` 前缀)。
- Provisioner(S2c)建企业 = 建 metalake + 标准 catalog 骨架。

### 负面 / 代价(接受)
- "列我组的数据集" = 列 catalog/schema 下 fileset 后按 `can()` 过滤(过滤而非 namespace 扫),规模可忽略。
- group 隔离无 namespace 结构性兜底,依赖 `can()` 正确 —— 但 can() 是单一出入口 + 有测试;且**跨企业(灾难级)仍是 metalake 硬隔离**,group(企业内软边界)用属性可接受。

### 落地说明
- v1 dev:fileset catalog 指向 **MinIO**(S3 兼容,复用 dev compose);真 OSS 在 test/cloud。`s3-endpoint` + `location: s3a://…`(Gravitino 要 HCFS/s3a)。
- 具体 REST 端点 / 镜像版本 / s3 bundle 依赖在 Plan 4 第一任务(Gravitino 探针)实测钉死。
