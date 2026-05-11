# ADR-008: 数据集元数据权威源 — 平台自维护，Hub 元数据仅作辅助字段

- 状态：Accepted
- 日期：2026-05-11
- 决策人：X-user team（P1/P2/P3）
- 相关：design doc §3.5 资产 URI / §3.7 元数据职责划分 / user-stories/tenant-team-scenarios.md（数据集与数据管线场景）/ ADR-007 PolicyEngine

## Context

数据集（Dataset）是 LLM infra 平台的核心资产，其元数据驱动多项关键决策：

- **训练复现性**：dataset URI 必须可固定到一个不变快照
- **配额计费**：`size_bytes` / `row_count` 是 OSS 容量配额和成本计算依据
- **法务合规**：`license` 决定数据集能否用于商用训练 / 二次分发
- **质量评估**：`schema` / `null_count` / `distinct_count` 影响训练数据质量判断
- **跨平台依赖**：dataset URI 被 training job / model / MLflow run / Argo Workflow 反向引用

**典型数据流向**：

```
外部 Hub（HuggingFace / Kaggle / ModelScope / arXiv / 内部上传）
  ↓ data fetch
raw/{tenant_id}/{name}/ (OSS)
  ↓ 数据管线（Argo + Ray + Data-Juicer）
processed/{tenant_id}/{name}.lance (OSS)
  ↓ 注册
Gravitino schema t_{tenant_id} + Lance VectorTable 抽象
```

注册到 Gravitino 后，dataset 进入 `active` 状态，被多方引用。

### 元数据来源的两条路径

| 路径 | 来源 | 示例字段 |
|---|---|---|
| **路径 A：信任 Hub 元数据** | 拉取时读 Hub 提供的 README / DataCard / parquet 元信息 | `row_count`、`schema`、`license`、`size_bytes` 都从 Hub 拿 |
| **路径 B：平台自分析** | 管线 ServiceAccount 扫描 Lance 文件，自己算 | 全部字段平台自算 |

### 决策矩阵

| 因素 | 路径 A（信 Hub） | 路径 B（自分析） |
|---|---|---|
| 准确性 | ❌ Hub 元数据常滞后 / 错填 / 格式不统一 | ✅ Scan 一遍 100% 准确 |
| 可信度 | ❌ 供应链风险：标错 license / 篡改 row_count | ✅ 单一可信源 |
| 成本 | ✅ 几乎零 | ⚠️ 多一次 scan，但管线本就要扫，边际成本接近 0 |
| 离线 / 自建场景 | ❌ 不可行（内网 / 跨云 / mirror 失效） | ✅ 任意环境可用 |
| Schema 一致 | ❌ HF / Kaggle / ModelScope 元数据 schema 各异，要写 N 个适配器 | ✅ 自家 schema 统一 |
| 法务 / 合规 | ⚠️ 上游 license 可能更新 / 表述模糊 | ✅ 注册时间点的快照 + 自家枚举 |
| 复现性 | ❌ Hub 上游可改 / 可删（数据集消失过的真实案例） | ✅ 入库即冻结 |
| 平台自主性 | ❌ 与上游强耦合 | ✅ 上游故障 / API 变更不影响本平台 |

## Decision

**v1 选 路径 B：平台自维护权威元数据；Hub 元数据保留但仅作辅助字段（不作权威源）**。

### 元数据字段分层

```
Gravitino schema t_{tenant_id} 中每个 dataset entity 含三类字段：

┌─────────────────────────────────────────────────────────────┐
│ Layer 1: 权威字段（平台自算，单一可信源）                    │
├─────────────────────────────────────────────────────────────┤
│  • tenant_id            (注册时记)                          │
│  • name, version        (用户/管线指定)                     │
│  • owner                (注册时记 user_id)                  │
│  • uri                  (gravitino://...)                   │
│  • lance_path           (oss://.../*.lance/)                │
│  • row_count            (Lance 写入时算)                    │
│  • size_bytes           (OSS 实际字节)                      │
│  • schema               (Lance 自扫)                        │
│  • column_stats         (Lance 写入时算：min/max/null/dist) │
│  • checksum             (Lance manifest)                    │
│  • created_at           (注册时间戳)                        │
│  • license_normalized   (平台枚举: apache-2.0 / mit / ...)  │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│ Layer 2: 派生属性（实时查询，非存储）                        │
├─────────────────────────────────────────────────────────────┤
│  • ref_count            (查 MLflow / Job / Model 引用)      │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│ Layer 3: 辅助字段 source.*（Hub 原始信息，不验证不作权威）  │
├─────────────────────────────────────────────────────────────┤
│  • source.kind          (huggingface / kaggle / upload)     │
│  • source.hub_url       (https://huggingface.co/.../...)    │
│  • source.hub_revision  (HF commit sha / Kaggle version)    │
│  • source.hub_license_raw  (原始 license 字符串，未规范化)  │
│  • source.hub_size_reported  (Hub 自报大小，与 size_bytes 对账) │
│  • source.fetched_at    (拉取时间戳，UTC)                   │
│  • source.notes         (其他原始 metadata，free-form JSON) │
└─────────────────────────────────────────────────────────────┘
```

### 写入规则（强约束）

1. **Layer 1 字段由数据管线 ServiceAccount 写入**：用户禁止直接填这些字段
2. **`license_normalized` 必须从平台枚举中选**（见下文 license 枚举），否则注册失败
3. **`source.*` 字段为非权威辅助**：UI 显示时必须标注"原始来源信息（未验证）"
4. **`source.hub_license_raw` 与 `license_normalized` 不一致** → 注册时 warn + 写 audit；不阻塞，由 owner 确认
5. **`source.hub_size_reported` 与 `size_bytes` 偏差 > 10%** → 注册时 warn + 写 audit
6. **dataset URI 必须含版本**：训练作业 `dataset_uri` 不允许引用 `latest` 浮动；强制 `@v1` / `@v2` 等显式版本

### License 枚举（v1 初始集，可演进）

```python
class License(str, Enum):
    APACHE_2_0      = "apache-2.0"
    MIT             = "mit"
    BSD_3_CLAUSE    = "bsd-3-clause"
    CC_BY_4_0       = "cc-by-4.0"
    CC_BY_SA_4_0    = "cc-by-sa-4.0"
    CC_BY_NC_4_0    = "cc-by-nc-4.0"      # 非商用
    CC0_1_0         = "cc0-1.0"            # 公共领域
    GPL_3_0         = "gpl-3.0"
    LGPL_3_0        = "lgpl-3.0"
    OPENRAIL        = "openrail"           # AI/ML 常用
    PROPRIETARY     = "proprietary"        # 平台内自有
    UNKNOWN         = "unknown"            # 兜底，需法务 review
```

新增 license 需走 PR + 法务签字。

### 派生属性 ref_count 的计算

```python
def get_ref_count(dataset_uri: str) -> int:
    return (
        count_training_jobs_referencing(dataset_uri)
        + count_mlflow_runs_with_param("dataset", dataset_uri)
        + count_models_with_lineage(dataset_uri)
        + count_pipelines_with_input(dataset_uri)
    )
```

- 实时查询，**不预计算 / 不缓存**（v1 规模查询成本低）
- v2 规模上升后可考虑事件驱动维护（写入端更新计数）

## Consequence

### 正面

- **复现性**：dataset 入库即冻结，上游 Hub 改名 / 删除不影响平台引用
- **跨云**：自家元数据独立于任何外部 Hub API
- **合规**：`license_normalized` 平台枚举，法务 review 工作量从"读每条原文"降为"看 enum 分布"
- **安全**：杜绝供应链风险（伪造 row_count / 错填 license）
- **配额准确**：`size_bytes` 自量，不被上游虚报误导
- **审计完整**：所有权威字段写入路径单一（管线 SA），易追溯

### 负面

- 注册时多一次扫描（成本接近 0，已经在跑管线）
- License 枚举法务 review 成本：v1 初始集 12 条，新增需走流程
- Hub 元数据保留但不信任 → UI 必须明确标"原始来源信息（未验证）"，否则用户混淆
- `ref_count` 实时查询：v1 规模够，v2 需评估缓存

### 中性

- `source.*` 辅助字段的 schema 演进自由（free-form JSON），不影响权威字段
- 平台不主动同步 Hub 上游更新（如 HF 改 license）：用户责任，UI 提示链接而已

## 实施约束（写入 spec：数据管线 + 数据集注册）

1. **管线注册接口签名只接收 Layer 1 + Layer 3 输入**，禁止 caller 传 `ref_count`
2. **`License` 枚举校验在 Gravitino 写入前**，校验失败返回 422 with reason
3. **`source.hub_license_raw` vs `license_normalized` 不一致** → 注册成功但事件 bus 发 warn 事件，audit log 记录
4. **dataset URI 解析**：`gravitino://my/{name}@{version}` 必须能解析到唯一 lance_path；`@latest` 在用户输入层（CLI/SDK）禁止
5. **删除时引用检查**：必须实时查 `ref_count`，禁止用注册时缓存
6. **CI 防线**：注册接口的 schema 校验单测覆盖率 100%

## v1 不做（v2 演进）

| 演进项 | v2 何时做 |
|---|---|
| Hub 上游变更订阅（webhook 通知 license 改动） | 当出现实际合规事故 |
| 跨 tenant 共享 `t-system` 内置数据集 | v2 加共享层 |
| Lineage（dataset → model → deployment 追溯图） | v2 接 OpenLineage |
| Dataset diff（v1 vs v2 schema 变更） | v2 数据版本管理需求出现时 |
| 自动质量评分（completeness / freshness / uniqueness） | v2 数据治理 |

## 后续动作

- [ ] Sprint 0a：在 spec 中明确 Gravitino schema 含 `source.*` namespace 字段（owner: P2）
- [ ] Sprint 0a：License 枚举初始集落地到代码 + 法务对齐（owner: P3）
- [ ] Sprint 1：数据管线注册接口实现 + Layer 1/3 字段写入逻辑（owner: P2）
- [ ] Sprint 1：`ref_count` 实时查询实现 + PolicyEngine 集成（owner: P3）
- [ ] Sprint 1：UI 标注"原始来源信息（未验证）"（owner: P1）
- [ ] v2 评估：ref_count 缓存策略 / Hub 变更订阅 / Lineage 接入
