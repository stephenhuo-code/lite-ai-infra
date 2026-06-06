# 用户故事：租户团队场景（v1）

- 适用范围：对外多企业 SaaS 的团队协作场景 — 角色能力边界与验收
- 关联：[constitution](../constitution.md) / ADR-010（多企业）/ ADR-011（Cerbos）/ ADR-012（Agent/LLM）/ design §3.2
- 用途：Cerbos 策略 + `can()` 的验收真相源 / Portal & SDK & CLI 行为契约 / 用户文档素材
- 日期：2026-05-10（**2026-06-06 升级到两级模型**）

> ⚠️ **已升级为多企业两级模型（2026-06-06）。下方"验收清单（AC 表）"是权威真相源；上方角色定义/一日故事/能力表为历史叙述（旧单层 tenant 模型），按下列映射读。**
>
> **层级与角色**：平台 → **企业(enterprise)** → **用户组(group)** → 用户。角色：
> - `member`：本组私有资源 owner 操作 + 读企业共享 + 读本组
> - `group-admin`：**仅管本组**（本组资源/成员）← 旧 `tenant-admin`（团队 lead）≈ 此
> - `enterprise-admin`：管本企业**所有组** + **写企业共享资源** + 配额（配额 vN+）
> - `platform-admin`：跨企业，仅走 `/admin/*` 特权 API
>
> **4 条语义裁定（2026-06-06）**：① group-admin 仅管本组；② 企业共享资源**企业内全读、仅 enterprise-admin 写**；③ 同企业**跨组私有资源默认隔离**；④ agent/LLM/检索**继承调用者 scope**。
>
> **授权分期**：v1 **薄 `can()`**（认证 + 企业隔离 + owner + 基本角色门槛，in-code）；v2 **Cerbos**（组 scope / 共享派生角色 / 派生属性 / agent scope）。数据路径（OSS）由 **RAM/STS** 执行。术语：`tenant→enterprise`、`tenant-admin→group-admin`、`t-00xx→e-00xx`、`cross-tenant→cross-enterprise`。

---

## 角色定义

| 角色 | 在 Keycloak 中的身份 | 典型代表 | 数量（v1） |
|---|---|---|---|
| **未登录访客** | 无 | 浏览器陌生用户、未登录的脚本 | 不限 |
| **普通成员**（tenant-member） | `lite-ai` realm 用户 + group `/tenants/{tenant_id}` | alice、bob | 十余人 |
| **tenant-admin** | `lite-ai` realm 用户 + group `/tenants/{tenant_id}` + role `tenant-admin` | X-user team lead | 1-2 人 |
| **platform-admin** | `master` realm 用户 + role `platform-admin` | P1 / P2 / P3 | 3 人 |

> v1 阶段，platform-admin 凭证锁在 1Password 团队保险柜，仅救火 / IaC apply 使用，禁止日常使用（详见 ADR-002）。

---

## 角色 1：普通成员 alice（X-user team / `tenant-member`）

### ✅ 能做的

| 能力 | 行为 | 验收点 |
|---|---|---|
| 登录平台 | `laictl login` 走 OIDC，浏览器跳 Keycloak | login 成功 + token 缓存 |
| 看本 tenant 的所有作业 | Portal 仪表盘 / `laictl job list` | 列表只含本 tenant 数据 |
| 看本 tenant 的推理 endpoint | Portal / `laictl inference list` | 含访问 URL（`*.t-0001.lite-ai.local`） |
| 看本 tenant 的 Workspace | Portal / `laictl workspace list` | 列表含状态 + 链接 |
| 看本 tenant 的 MLflow 实验 | Portal 跳 MLflow / 直接访问 MLflow UI | 同 tenant 队友的 run 都可见 |
| 看本 tenant 的配额使用 | Portal 显示 GPU 卡时 / OSS 用量 | 数字可读 |
| 提交训练作业（≤ 4 GPU） | `laictl train submit --gpu 4 --dataset gravitino://my/v1` | 作业进入 Volcano 队列 |
| 部署推理服务 | `laictl inference deploy --model gravitino://my/m1` | endpoint 上线 |
| 起 Workspace | `laictl workspace create` 或 Portal 按钮 | 浏览器 VSCode 可访问 + SSH 可登 |
| 删自己的作业（running） | `laictl job delete <id>` | 作业被 kill |
| 进自己的 Workspace | 浏览器 VSCode / SSH | 进入容器 |
| 下载本 tenant 的 checkpoint | `laictl checkpoint pull <run_id>` | OSS 拉取成功 |
| 查日志 | Grafana 仪表盘（datasource 已带 tenant_id 过滤） | 仅看到 `tenant_id=t-0001` 的日志 |
| 改密码 / 加 MFA | 浏览器跳 Keycloak Account Console | Keycloak 自己处理，平台不参与 |

### ❌ 不能做的

| 场景 | 平台行为 | 错误信息（建议） |
|---|---|---|
| 删队友 bob 的训练作业 | 拒 | `only owner or tenant-admin can delete` |
| SSH 进 bob 的 Workspace | 拒 | `Workspace 仅 owner 可访问` |
| 下载其他 tenant 的 checkpoint | 拒 | `cross-tenant access denied`（OSS RAM 也直接拒） |
| 训练里引用 t-0099 的数据集 URI | 拒 | `dataset 不属于当前 tenant` |
| 看 t-0099 的 MLflow 实验 | 列表中不出现 | 列表为空（不抛错，避免泄漏存在性） |
| 删已 completed 的作业 | 拒 | `已完成作业不能删除，请使用 archive` |
| 提交 8 GPU 的大作业 | 拒 | `> 4 GPU 大作业需要 tenant-admin 角色` |
| 加新成员到本 tenant | 拒 | `仅 tenant-admin 可管理成员` |
| 看平台总览 dashboard | 入口不显示 | — |
| 登 Keycloak Admin Console | 拒 | Keycloak 直接拒 |

### 一日故事：alice 的一天

```
09:00  alice 打开 Portal → 跳 Keycloak 登录（密码 + MFA）
       Portal 显示：
         · 我的作业：3 个 running，1 个 completed
         · 我的数据集：5 个 active
         · 我的管线：1 个 running
         · 配额：GPU 30/100 卡时；OSS 1.2/5 TB
         · 推理 endpoint：inf-mymodel.t-0001（健康）

09:15  上传新的 50GB 图文原始数据
       laictl data upload ./local-data/ --to raw/poster-corpus
       ✅ 写入 oss://lite-ai-infra/raw/t-0001/poster-corpus/

09:30  提交清洗管线
       laictl pipeline submit \
         --template image-text-clean \
         --input  raw/poster-corpus \
         --output processed/poster-corpus
       ✅ 配额预检通过（OSS 流量 100GB / CPU 8h），Argo Workflow 进入 pending

09:45  CLI 用已有数据集提交 4-GPU 训练
       laictl train submit --gpu 4 --dataset gravitino://my/corpus-v1
       ✅ 通过 — 配额够、tenant 内数据集、≤ 4 卡

10:00  尝试 8-GPU 训练
       laictl train submit --gpu 8 --dataset gravitino://my/corpus-v1
       ❌ "> 4 GPU 大作业需要 tenant-admin 角色"
       → 找 lead 代提

10:30  Workflow running 中，alice 想改清洗参数
       laictl pipeline update <id> --param min-resolution=512
       ❌ "管线 running 后不可修改，请 cancel 重跑"

11:00  尝试拉隔壁 tenant 的预训练模型 / 数据集
       laictl model pull gravitino://t-0099.bert-base
       ❌ "cross-tenant access denied"
       laictl data pull gravitino://t-0099.imagenet
       ❌ "cross-tenant access denied"

11:30  误操作：手贱想直接写 processed/ 区跳过管线
       laictl data upload ./fake.lance --to processed/quick-hack
       ❌ "read-only — processed/ 仅由管线 ServiceAccount 可写"

12:00  管线 succeeded
       laictl pipeline status <id>
       → 输出: oss://.../processed/t-0001/poster-corpus.lance/
       Gravitino 自动注册 gravitino://my/poster-corpus@v1（owner = alice）

14:00  删昨天 completed 的训练作业
       laictl job delete <id>
       ❌ "已完成作业不能删除，请使用 archive"
       → laictl job archive <id>
       ✅ 通过

15:00  清理上周一个旧 dataset
       laictl data delete gravitino://my/old-corpus@v1
       ❌ "dataset 被 2 个资源引用：[run-x, model-y]，请先解除"
       → laictl data delete gravitino://my/old-corpus@v1 --dry-run
         看到引用方后通知队友 → 解除引用 → 重试 ✅

16:00  取消别人的管线（误以为是自己的）
       laictl pipeline cancel <bob-pipeline-id>
       ❌ "only owner or tenant-admin can cancel"

17:00  改密码 + 开 MFA
       浏览器跳 Keycloak Account Console
       ✅ 通过
```

---

## 角色 2：tenant-admin（X-user team lead / `tenant-admin`）

> 比普通成员多"管自家"的权限。**仍受 tenant 边界约束**，跨 tenant 一律拒。

### ✅ 比普通成员多能做的

| 能力 | 行为 | 验收点 |
|---|---|---|
| 管本 tenant 成员 | 邀请 / 移除（Portal 成员页 / `laictl member add\|remove`） | Keycloak group 自动同步 |
| 删队友的作业 | `laictl job delete <id>`（即使 owner ≠ 自己） | running 作业被 kill |
| 提交大作业（> 4 GPU） | `laictl train submit --gpu 8 ...` | 作业进入队列 |
| 看本 tenant 配额详情 | Portal → 配额页 | 含历史趋势 + 单作业用量 |
| 查本 tenant 的 audit log | Portal → 审计页 / `laictl audit list` | 仅本 tenant 操作记录 |

> v1 暂不开放"进队友 Workspace 救火"。X-user team 决策后开放则归此类。

### ❌ 仍然不能做的

| 场景 | 错误信息 |
|---|---|
| 看 / 操作 t-0099 的任何东西 | `cross-tenant access denied` |
| 自己给自己加配额 | 找 platform-admin 申请；admin 路径无入口 |
| 创建新 tenant | `/admin/tenants` 是 platform-admin 路径 |
| 登 Keycloak Admin Console | 拒 |
| 删 platform 级资源（kueue ClusterQueue 等） | 拒 |

### 一日故事：lead 的一天

```
09:00  收到 bob 失控训练通知
       laictl job delete <bob-job-id>
       ✅ 通过 — admin 能删本 tenant 任何人的作业

09:30  alice 上来求救：她的 8-GPU 训练被拒，需要 lead 代提
       laictl train submit --gpu 8 --dataset gravitino://my/corpus-v1 --on-behalf alice
       ✅ 通过 — admin 允许大作业（作业归属仍记 alice）

10:00  新人 carol 入职
       Portal → 成员页 → 邀请 carol@x-user.com
       ✅ 通过（Keycloak group 自动加入；carol 获得 tenant-member 角色）

10:30  bob 跑了个失控的清洗管线（OSS 流量飙升报警）
       laictl pipeline cancel <bob-pipeline-id>
       ✅ 通过 — admin 能取消任何成员的管线

11:00  离职同事 dave 留下一个被引用的 dataset，alice 要清理
       alice 自己删失败（owner ≠ alice），找 lead
       laictl data delete gravitino://my/dave-corpus@v1 --force
       ✅ 通过 — tenant-admin + --force 跳过 owner 检查；ref_count=1 > 0
          → 数据集状态转为 deprecated（OSS 数据保留，阻止新作业引用）
          audit 写入：action=dataset.deprecate, override=true, 引用快照 [model-x]
       后续：model-x 被删除后 ref_count 降为 0
          → nightly GC 自动完成硬删，或 `laictl data delete gravitino://my/dave-corpus@v1` 再次触发

12:00  想给自己加配额
       Portal 只读显示配额，没有"改"按钮
       → 走流程找 platform-admin

14:00  好奇隔壁 tenant 的训练进度 / dataset 列表
       ❌ "cross-tenant access denied" — admin 也只管本 tenant

15:00  Portal 看本 tenant 数据集存储成本
       发现 raw/ 区累积了 800GB 过期上传，提醒队友清理
       (lead 不直接动队友的 dataset；只发通知)
```

---

## 角色 3：platform-admin（P1 / P2 / P3 / `master` realm admin）

> 最高权限，但**必须走 `/admin/*` 专用路径**。普通业务路径下也按 tenant 隔离走（避免误操作）。

### ✅ 比 tenant-admin 多能做的

| 能力 | 行为 | 验收点 |
|---|---|---|
| 创建租户 | `laictl --admin tenant create --id t-0099 --display "Y-team"` | Tenant Service 自动 provision 全部资源（见下方 provision 清单） |
| 暂停 / 归档租户 | `laictl --admin tenant suspend\|archive <id>` | tenant 状态变更，所有用户被禁用 |
| 跨 tenant 看东西 | Portal `/admin/*` 路径下的总览 dashboard | GPU 总用量 / 各 tenant 计费 / 平台健康 |
| 改 tenant 配额 | `laictl --admin tenant quota update t-0001 --gpu 500` | Capsule Tenant CR + Kueue LocalQueue 同步更新 |
| 跨 tenant 救火 | 在 `/admin/*` 路径删任何 tenant 的作业 / 进任何 Workspace | 操作进 audit log 标 admin override |
| 登 Keycloak Admin Console | master realm admin 账号 | 仅救火 / IaC 出错排查 |
| Apply Realm IaC 到 prod | 双签 → `keycloak-config-cli apply --env prod` | apply 成功 + dry-run diff 入 PR |
| 看平台总览 dashboard | Grafana platform-admin org | 跨 tenant 视图 |

#### 创建 tenant 时 Tenant Service 自动 provision 的资源

| 资源 | 系统 |
|---|---|
| Tenant 元数据记录 | PG |
| Group `/tenants/{tenant_id}` | Keycloak |
| Capsule Tenant CR | K8s |
| Namespace + ResourceQuota + NetworkPolicy + RBAC | Capsule 自动下发 |
| Kueue LocalQueue | K8s |
| OSS Prefix + RAM 子账号 | OSS / RAM |
| Gravitino Schema | Gravitino |
| MLflow Experiment | MLflow |
| Grafana Datasource / Org | Grafana |
| OpenSearch Index Template | OpenSearch |

### ❌ 仍然不能做的（出于安全设计）

| 场景 | 平台行为 |
|---|---|
| 用普通业务 API 跨 tenant 操作（在 `POST /v1/training/jobs` body 里塞别 tenant 的 ID） | 拒 — 普通路径下 platform-admin 也走 tenant 隔离规则；必须显式走 `/admin/*` |
| Keycloak Admin Console 手工改 group / client | 纪律禁止 — 所有变更必须走 IaC（keycloak-config-cli） |
| master admin 凭证日常使用 | 纪律禁止 — 仅救火 / IaC apply |
| 跳过 audit log 操作 | 不可能 — admin override 类操作强制写 audit |

### 一日故事：你（platform-admin）的一天

```
09:00  X-user team 申请加 GPU + OSS 配额（最近数据集多了）
       laictl --admin tenant quota update t-0001 --gpu 500 --oss-bytes 10TB
       ✅ 通过 — 走 /admin/* 特权 path（Capsule + OSS bucket policy 同步）

10:00  新 tenant 申请
       laictl --admin tenant create --id t-0099 --display "Y-team"
       Tenant Service 自动 provision 10 项资源（Keycloak group / Capsule CR /
       OSS prefix + RAM 子账号 / Gravitino schema / MLflow experiment /
       Kueue LocalQueue / Grafana datasource / OpenSearch index template ...）
       ✅ 全部完成，audit log 记录

11:00  容量审计：跨 tenant 看数据集存储用量
       laictl --admin data list --all-tenants --by-size
       发现 t-0099 有一个 dataset 的 owner 已离职 + 30 天无引用
       laictl --admin data gc gravitino://t-0099.legacy-corpus@v0 --reason "孤儿数据集"
       → 二次确认 → ✅（强 audit + 标 admin gc）

11:30  Realm 配置变更（加一个新 client）
       改 base.yaml → PR → 双签 → apply staging（dry-run + 验证）→ apply prod
       ✅ 通过

13:00  ACK 节点维护通知：某 GPU 节点要下线 2h
       laictl --admin pipeline cancel <某 t-0099 管线 id> --reason "GPU 节点维护"
       ✅ 通过 — admin 可跨 tenant 救火（audit 标 admin override + 含 reason）

14:00  误操作演练
       用 alice 账号往 POST /v1/training/jobs 塞 tenant_id=t-0099
       ❌ "cross-tenant access denied"
          普通业务 path 下 platform-admin 也按 tenant 隔离走
       同样的普通 path 尝试读 t-0099 的数据集
       ❌ 直 OSS RAM 拒（不到 PolicyEngine）

15:00  Keycloak 救火（某 client 配错）
       1Password 取 master admin 凭证 → Admin Console
       手工改 → ❌ 内部纪律禁止（被 IaC 下次 apply 覆盖）
       → 改 IaC 仓库的 base.yaml → apply → 修好
       关 Admin Console，凭证回 1Password
```

---

## 角色 4：未登录访客

### ✅ 能访问的

| 路径 | 用途 |
|---|---|
| Portal `/`（未登录视图） | 跳转 Keycloak 登录 |
| Platform API `/healthz` | K8s readiness/liveness 探针 |
| Keycloak `/realms/lite-ai/.well-known/*` | OIDC discovery |

### ❌ 不能做的

| 场景 | 平台行为 |
|---|---|
| 调任何业务 API（不带 token） | `401 Unauthorized` |
| 访问推理 endpoint（即使知道 URL） | Ingress OIDC 拦截 → 跳 Keycloak |
| 访问 Workspace | 同上 |
| 访问 Grafana / MLflow | 同上 |

---

## 数据集与数据管线场景

数据集（Dataset）和数据管线（Pipeline）权限模型与训练作业 / 推理 / Workspace 略有不同，单独细化。

### 资源关系

```
   原始上传文件                   数据管线（Argo + Ray + Data-Juicer）              已注册数据集
   (raw, OSS)        ────清洗───▶ (Argo Workflow + Ray Data 任务)        ──产物──▶ (Lance + Gravitino)
                                          │
                                          └─ 状态: pending / running / failed / succeeded
   tenant_id 标记于:                       │                                       tenant_id 标记于:
   · OSS prefix raw/{tenant_id}/           │                                       · Gravitino schema t_{tid}
                                                                                   · OSS prefix processed/{tid}/
                                                                                   · Lance dataset URI
                                                                                     gravitino://{tid}.{name}@{ver}
```

### 关键权限差异点

1. **数据集是"资产"**：相比"作业"，数据集生命周期更长、更值钱，删除门槛更高
2. **数据集可有引用关系**：训练作业 / 管线产物 / 模型可能引用某 dataset；删除前要查引用
3. **数据管线可能很贵**：跑 10TB 清洗一次 = 几小时 GPU/CPU + OSS 流量；提交前必须配额预检
4. **管线一旦 running 不可改**：参数固化，要么 cancel 重跑、要么等完成
5. **数据集"私有"语义**：v1 全 tenant 内可见（不分 owner），但**删除/重命名/版本发布**只能 owner 或 tenant-admin

---

### 普通成员 alice（tenant-member）

#### ✅ 数据集

| 能力 | 行为 | 验收点 |
|---|---|---|
| 上传原始数据到本 tenant raw 区 | `laictl data upload ./local/* --to raw/my-corpus` | OSS 写入 `raw/{tenant_id}/my-corpus/`；写入受 OSS RAM 子账号 policy 约束 |
| 列本 tenant 的所有数据集 | `laictl data list` / Portal 数据集页 | 含别人创建的（v1 tenant 内全可见） |
| 看数据集详情 | `laictl data describe gravitino://my/corpus@v1` | schema、行数、Lance 路径、引用方 |
| 下载数据集（pull 整个或采样） | `laictl data pull gravitino://my/corpus@v1` | OSS 读权限 OK |
| 注册新数据集（自己上传/清洗后的产物） | `laictl data register --uri ... --name corpus --version v1` | Gravitino schema 写入；owner = alice |
| 删自己注册的数据集（无引用） | `laictl data delete gravitino://my/my-corpus@v1` | Gravitino + OSS 同步删除 |

#### ✅ 数据管线

| 能力 | 行为 | 验收点 |
|---|---|---|
| 用平台模板提交清洗管线 | `laictl pipeline submit --template image-text-clean --input raw/my-corpus --output processed/my-corpus` | Argo Workflow 入队；自动配额预检（OSS 流量 + CPU/GPU 时） |
| 看本 tenant 所有管线状态 | `laictl pipeline list` / Portal 管线页 | 含别人提交的 |
| 看管线日志 / step 进度 | `laictl pipeline logs <run_id>` | 仅本 tenant 数据，OpenSearch 软隔离 |
| 取消自己提交的 running 管线 | `laictl pipeline cancel <run_id>` | Argo cancel + Ray cluster 释放 |
| 重跑自己 failed 的管线（同参数） | `laictl pipeline retry <run_id>` | 新 run，配额重新预检 |

#### ❌ 不能做的

| 场景 | 错误信息 |
|---|---|
| 删别人注册的数据集 | `only owner or tenant-admin can delete dataset` |
| 删被引用的数据集（被某 run / model 引用） | `dataset 被 N 个资源引用，请先解除` + 引用列表 |
| 改别人的数据集元数据（rename / 改 schema） | `only owner or tenant-admin can modify` |
| 发布 public version（如 v1 → release v1.0） | v1 不开放此动作；v2 评估 |
| 取消别人的 running 管线 | `only owner or tenant-admin can cancel` |
| 改别人 pending 管线的参数 | `only owner can modify before running`（且 v1 不允许任何人在 running 后改） |
| 引用 t-0099 的数据集 | `cross-tenant access denied` |
| 跑超出配额的大管线（>500GB OSS 流量等） | `quota exceeded: oss_traffic`（提交时拒，不是 running 中拒） |
| 直接写 OSS `processed/` 区（绕过管线） | `read-only` — `processed/` 仅由 Argo Workflow 的 ServiceAccount 可写 |

---

### tenant-admin（X-user team lead）

#### ✅ 比普通成员多能做的

| 能力 | 行为 | 备注 |
|---|---|---|
| 废弃队友注册的数据集（含被引用） | `laictl data delete <uri> --force` | ref_count>0 时转为 `deprecated`（OSS 保留、阻止新引用）；ref_count==0 时直接硬删；写 audit + 引用快照 |
| 改任何队友的数据集元数据 | `laictl data update <uri> --name newname` | rename / 改描述 |
| 取消任何队友的 running 管线 | `laictl pipeline cancel <run_id>` | — |
| 提交超大管线（> 默认配额阈值） | `laictl pipeline submit --large` | 仍受 tenant 总配额约束 |
| 看本 tenant 数据集存储成本 | Portal 数据集页 → 成本列 | 计费视图 |

#### ❌ 仍然不能做的

| 场景 | 错误信息 |
|---|---|
| 看 / 拷贝 t-0099 的数据集 | `cross-tenant access denied` |
| 删 platform 预置的公共数据集（v2 才有） | v1 不存在；v2 受 platform-admin 控制 |
| 改全 tenant 数据集存储配额 | 找 platform-admin |

---

### platform-admin（admin path）

#### ✅ 比 tenant-admin 多能做的

| 能力 | 行为 | 备注 |
|---|---|---|
| 跨 tenant 看数据集列表（容量审计） | `laictl --admin data list --all-tenants` | 仅元数据 + 大小，不含内容 |
| 删任何 tenant 的"孤儿数据集"（owner 已离职 + 无引用） | `laictl --admin data gc <uri>` | 强 audit + 二次确认 |
| 调整 tenant 数据集存储配额 | `laictl --admin tenant quota update t-0001 --oss-bytes 10TB` | Capsule + OSS bucket policy 同步 |
| 跨 tenant 取消 running 管线（救火） | `laictl --admin pipeline cancel <run_id> --reason "GPU 节点维护"` | audit 标 admin override |
| 创建/管理平台预置管线模板（v2 才有） | — | v1 不做 |

#### ❌ 仍然不能做的（出于安全设计）

| 场景 | 平台行为 |
|---|---|
| 用普通业务 API 操作其他 tenant 的数据集 | 拒 — 必须走 `/admin/*` |
| 直接读 t-0001 数据集内容（不经 admin path） | 拒 — 即便有 master admin 凭证，OSS RAM 也按 tenant 子账号隔离 |
| 跳过 audit log 的数据集删除 | 不可能 — 强制 audit |

---

### v1 不做的（v2 演进）

| 场景 | v2 何时做 |
|---|---|
| 数据集 owner 转移（alice → bob） | 当 v1 出现"成员离职导致孤儿数据集"实际痛点时 |
| 数据集 / 管线模板的 tenant 内 ACL（部分队友可见） | 当 X-user team 出现保密需求时 |
| Public 数据集（跨 tenant 共享） | v2 加 `t-system` 命名空间后 |
| 数据集打 release tag / pin 版本（不可删） | 当出现训练复现需求时 |
| 数据管线的细粒度权限（如"只能用某模板"） | 当模板复杂度上升时 |
| 数据 lineage 可视化（哪个 model 来自哪个 dataset） | v2 接 OpenLineage |

---

## 验收清单（spec 001-tenant-identity 引用此节）

PolicyEngine 必须通过的端到端测试：

> **场景设定**：alice、bob 同属企业 `e-0001` 的用户组 `g-0001`；`g-0002` 是同企业另一组；`e-0099` 是另一家企业。**授权层**：`v1`=薄 can()（认证/企业隔离/owner/角色门槛）｜`v2`=Cerbos（组 scope/共享/派生属性/agent）｜`数据层`=RAM/STS 或 query 过滤｜`vN+`=推迟。

| # | 测试场景 | 期望 | 授权层 |
|---|---|---|---|
| **作业 / 通用** | | | |
| AC-1 | alice 删自己的 running 作业 | ✅ | v1(owner) |
| AC-2 | alice 删同组 bob 的 running 作业 | ❌ `only owner / group-admin / enterprise-admin` | v2(owner) |
| AC-3 | alice 删自己的 completed 作业 | ❌ `已完成作业不能删除` | v2(state) |
| AC-4 | alice 提交 4 GPU 作业 | ✅ | v1 |
| AC-5 | alice 提交 8 GPU 作业 | ❌ `> 4 GPU 需 group-admin+ 角色` | v1(role) |
| AC-6 | alice 引用 e-0099 数据集 | ❌ `cross-enterprise` | v1(企业隔离) |
| AC-7 | alice 列 MLflow run | 仅本企业、本组私有 + 企业共享可见 | v2(scope)+数据层过滤 |
| AC-8 | alice OSS 直读 e-0099 路径 | ❌ RAM/STS 拒（不到 PDP） | 数据层(STS) |
| **用户组管理员（group-admin，仅本组）** | | | |
| AC-9 | group-admin 删本组队友作业 | ✅ | v2(group) |
| AC-10 | group-admin 提交 8 GPU | ✅ | v1(role) |
| AC-11 | group-admin 加本组成员 | ✅ | Keycloak + v2(group) |
| AC-12 | group-admin 改配额 | ❌ `requires enterprise-admin+`（配额 vN+） | vN+ |
| AC-13 | group-admin 看 e-0099 | ❌ `cross-enterprise` | v1 |
| **platform-admin（仅 `/admin/*`）** | | | |
| AC-14 | platform-admin 走 `/admin/*` 创建 enterprise | ✅ + provision（Org+Group+资源） | v1 / Provisioner |
| AC-15 | platform-admin 走普通业务 path 跨企业 | ❌ `cross-enterprise`（强制走 /admin/*） | v1 |
| AC-16 | platform-admin 改企业配额（admin path） | ✅（配额 vN+） | vN+ |
| AC-17 | platform-admin override 删任何作业 | ✅ + audit 记录 override | v1(特权)+审计 |
| **未登录** | | | |
| AC-18 | 未登录访 `/v1/*` | `401` | v1(认证) |
| AC-19 | 未登录访推理 endpoint | Ingress 跳 Keycloak | v1 |
| AC-20 | 未登录访 `/healthz` | `200` | 白名单 |
| **数据集** | | | |
| AC-21 | alice 注册自己（本组）的数据集 | ✅ | v1 |
| AC-22 | alice 删自己的数据集（无引用） | ✅ | v2(owner+ref) |
| AC-23 | alice 删自己的数据集（被 2 个 run 引用） | ❌ `dataset 被 N 个资源引用` | v2(ref) |
| AC-24 | alice 删同组 bob 的数据集 | ❌ `only owner / group-admin+` | v2(owner) |
| AC-25 | alice 改同组 bob 的数据集 schema | ❌ `only owner / group-admin+` | v2 |
| AC-26 | alice 引用 e-0099 数据集（OSS 直读 + URI 双路径） | ❌ `cross-enterprise`（RAM/STS + PDP 双拒） | v1 + 数据层 |
| AC-27 | group-admin `--force` 废弃本组队友数据集（ref_count>0） | ✅ 转 deprecated + audit（OSS 保留，不硬删） | v2 |
| **数据管线** | | | |
| AC-28 | alice 提交管线（配额内） | ✅ | v1 |
| AC-29 | alice 提交管线（OSS 流量超配额） | ❌ `quota exceeded`（**vN+；v1 仅 Kueue 静态配额**） | vN+ |
| AC-30 | alice 改 running 管线参数 | ❌ `running 后不可修改` | v2(state) |
| AC-31 | alice 取消同组 bob 的 running 管线 | ❌ `only owner / group-admin+` | v2(owner) |
| AC-32 | alice 重跑自己 failed 管线 | ✅ | v1/v2 |
| AC-33 | alice 直接写 OSS `processed/` 区 | ❌ RAM/STS 拒（仅管线 SA 可写） | 数据层 |
| AC-34 | platform-admin gc 孤儿数据集 | ✅ + audit + 二次确认 | v1(特权) |
| AC-35 | alice 改同组 bob 的 pending 管线参数 | ❌ `only owner / group-admin+` | v2 |
| **Workspace** | | | |
| AC-36 | group-admin 进队友 Workspace（v1） | ❌ `Workspace 仅 owner 可访问（v1）` | v1/v2 |
| **用户组 / 企业共享（两级模型新增）** | | | |
| AC-37 | alice(g-0001) 访问 g-0002 的私有资源 | ❌ `cross-group`（同企业跨组默认隔离） | v2(group scope) |
| AC-38 | alice 读企业共享数据集（scope=shared） | ✅（企业内全读） | v2(shared 派生角色) |
| AC-39 | alice(member) 写/发布到企业共享区 | ❌ `requires enterprise-admin` | v2 |
| AC-40 | enterprise-admin 写企业共享区 | ✅ | v2 |
| AC-41 | enterprise-admin 管本企业任意组（建组/移成员） | ✅ | v2(enterprise scope) |
| **Agent / LLM（v2，ADR-012）** | | | |
| AC-42 | agent / Agentic Search 以 alice 身份检索 | 仅返回 alice 可见（本组私有 + 企业共享），**不越权**；经 can()+数据层过滤 | v2(scope 继承) |
| AC-43 | LLM Gateway 调用按 enterprise/group 计量；越权模型/超限 | 计量记录；拒越权或超限 | v2 |

---

## 状态转换的 PolicyEngine 行为（参考）

| 资源 | 状态 | 普通成员可做 | tenant-admin 可做 | platform-admin（admin path）可做 |
|---|---|---|---|---|
| 训练作业 | running | view, cancel(own), retry(own) | view, cancel(any), retry(any) | view, cancel, override |
| 训练作业 | completed | view, archive(own), pull artifacts(any) | view, archive(any) | view, override |
| 训练作业 | archived | view (read-only) | view, restore | view, restore, delete |
| 推理 Deployment | healthy | view, scale(own), tear-down(own) | view, scale(any), tear-down(any) | view, override |
| Workspace | running | enter(own), stop(own) | view list（不进 v1） | enter(any), stop(any) |
| Workspace | stopped | start(own), delete(own) | delete(any) | delete(any) |
| 数据集 | active | view, pull, register, delete(own)[1], update(own) | view, pull, deprecate(any)[1] `--force`, update(any) | view, pull, gc(orphan)[1] + 强 audit |
| 数据集 | deprecated | view, pull（只读） | view, pull, delete（ref_count==0 时）[1] | view, pull, gc（强删，含 ref_count>0）[1] + 二次确认 |

> [1] **delete / deprecate 决策依赖派生属性 `ref_count`**（实时查 Gravitino lineage 边），不是唯一状态：
> - `ref_count == 0`：owner / admin 可直接硬删（OSS + Gravitino 同步删除）
> - `ref_count > 0` + 普通成员：拒（`dataset 被 N 个资源引用`）
> - `ref_count > 0` + `--force` + owner/tenant-admin：转 `deprecated`（OSS 保留；阻止新引用；现有引用只读）；audit 写引用快照（**不硬删，不跳 ref_count**）（AC-27）
> - `deprecated` + `ref_count == 0`：nightly GC 自动完成硬删，或 owner/admin 手动触发
> - `deprecated` + `ref_count > 0` + platform-admin gc（`/admin/*`）：强制硬删（最高破坏性）；强 audit + 二次确认（AC-34）
>
> [2] **训练作业 archived 状态**：`restore`（archived → active）仅 tenant-admin+；`delete(永久)`（销毁作业元数据 + artifact）仅 platform-admin；普通成员 archived 只读。
| 数据管线 | pending | view, cancel(own), update params(own) | view, cancel(any), update(any) | view, cancel + override |
| 数据管线 | running | view, cancel(own); 不可改参数 | view, cancel(any); 不可改参数 | view, cancel + override |
| 数据管线 | failed | view, retry(own) | view, retry(any) | view, retry, override |
| 数据管线 | succeeded | view (read-only); 产物 dataset 自动注册 | view; 产物归属 owner | view, override |

---

## 不在 v1 范围（v2 演进）

| 场景 | 当前不做 | 何时做 |
|---|---|---|
| 跨 tenant 资源共享（如平台预置数据集） | 暂无 | v2，加 `t-system` 命名空间语义 |
| 细粒度 dataset / model 级 ACL | 全 tenant 内可见 | 当 tenant 内有保密需求时 |
| 工作时间外限制大作业（环境属性） | 不启用 | 当夜间 GPU 闲置成本明显时 |
| IP allowlist 限制 admin path | 不启用 | 当出现合规需求时 |
| tenant-admin 进队友 Workspace 救火 | 默认拒 | X-user team 决策后开放 |
| 委托权限（delegate） | 暂无 | v2 评估，可能引入 ReBAC |
| service-account 自动化访问 | 仅手工 user 账号 | v2，加 client_credentials 流程 |

---

## 相关文档

- [Design Doc §3.2 多租户机制](../superpowers/specs/2026-05-08-llm-infra-platform-design.md)
- [ADR-002 Keycloak v1 单副本](../adr/ADR-002-keycloak-v1-single-replica.md)
- [ADR-005 OpenSearch 日志栈](../adr/ADR-005-logging-stack-opensearch.md)
- [ADR-007 PolicyEngine](../adr/ADR-007-access-control-policy-engine.md)
