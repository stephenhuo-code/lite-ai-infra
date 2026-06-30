# Design(设计):智能体库(Agent Library)

> 设计层(HOW)。对应 [spec.md](./spec.md)。决策落 [ADR-027](../../../adr/ADR-027-agent-library.md)。承接 9a [ADR-026](../../../adr/ADR-026-omnigent-integration.md)。
> **核心原则**:智能体的**企业归属与授权全在我们 BFF 做**,omnigent 保持租户无关;只给 omnigent 补一个它**自身已有逻辑**的运行时入口(小 fork)。

## 架构

### 拓扑(在 9a 之上加一层)
```
浏览器(前端:智能体库页 + 对话选择器)
   │ 同源,经 8090 网关
   ▼
BFF(唯一信任边界)
   ├─ GET  /v1/ws/agents          列:omnigent 全量 → 按企业过滤(内置模板 + 本企业)
   ├─ POST /v1/ws/agents          建:enterprise-admin(can())→ 搭 bundle → 调 omnigent → 记归属 + 审计
   ├─ POST /v1/ws/sessions         建会话:校验 agent 属本企业或内置 → JSON managed 建会话
   └─ (不反代 switch-agent → "开始后锁定")
   ▼
omnigent server(我们 fork)
   ├─ GET  /v1/agents              原生(列模板,无租户)
   ├─ POST /v1/agents  ★新(小 fork)暴露已有的 _ensure_builtin_agent → 建可复用模板
   └─ POST /v1/sessions {agent_id,host_type:managed}  原生(managed 沙箱,9a 已通)
```

- **模块边界**:omnigent = 租户无关的"智能体存储 + 运行时";**企业隔离、授权、审计 = BFF**。前端只经网关同源,碰不到 omnigent。
- **宪法一致**:§1 隔离(BFF 按企业过滤 + 建会话校验)、§2.4 授权经 `can()`、§5.2 无新 secret(全局共享订阅)、§6.1 审计、§5.3 parity(fork 自编译)。

### 小 fork:`POST /v1/agents`(探针钉死,ADR-027)
- omnigent **故意无运行时建 agent 端点**;但启动期内部函数 `_ensure_builtin_agent(agent_store, artifact_store, agent_cache, name, bundle_bytes)` 已完整(seed 那 11 个内置模板用的就是它)。
- fork 在 `omnigent/server/routes/builtin_agents.py` 加 `@router.post("/agents")`:收 multipart `bundle`(.tar.gz)→ 校验 spec → 调 `_ensure_builtin_agent` → 返回 `AgentObject`(含 `id`)。**纯加法、复用现成逻辑、不碰内部接线、可 upstream**。
- 端点照 omnigent 现有 header-auth(BFF 注入身份);**真正"谁能建"在 BFF**(omnigent 不懂企业管理员)。
- fork 流程:`third_party/omnigent`(liteai-9a)提交 + 单测 → `scripts/omnigent_build.sh dev` 重编译 server 镜像 → bump submodule。

## 数据模型

### 智能体(omnigent 原生 + 我们打标签)
- omnigent `Agent`(原生):`id / name / description / harness / version / ...`;store **无 owner/tenant 字段**;`GET /v1/agents` 返回 `name/description/harness` 等(**无 labels/metadata**,探针实测)。
- **企业归属编码**(§1.5"归属编码在资源自身"):**BFF 在创建时把 enterprise alias 编进 omnigent agent 的 `name`**,作结构化前缀。
  - **实测约束**:omnigent 的 name 校验器 = `^[a-zA-Z0-9_-]+$`(**仅 ASCII** 字母数字 + `_` + `-`;无点/斜杠/空白/控制符/非 ASCII)。故:
    - (a) **分隔符 SEP = `_`**(ASCII 下划线)。早先设想的 `␟`(U+001F)是控制符,会被 omnigent 400 拒;
    - (b) **`name = "<alias>_<ascii-id>"`** —— name 只承载【企业归属】+ 一个 ASCII id(无人类展示名);
    - (c) **人类展示名(任意 Unicode,可含中文)落 `description`**:首行 = 展示名,空行后(可选)= 用户描述,读时拆回(展示名根本进不了 name 字段);
    - (d) **不变量:enterprise alias 必须 `_`-free**(`^[a-zA-Z0-9-]+$`)—— 否则 `name.partition("_")[0]` 会错切前缀、可能跨企业泄漏。由 BFF `_resolve_ctx` 的 guard 强制(不符 → 409),覆盖 create/list/session-create。
  - **不变量**:有前缀(`_` 分隔)= 属该企业、仅该企业可见;**无前缀 = 内置模板(全局共享)**(内置名如 `*-native-ui` 用连字符,不含 `_` → 不误判)。
  - 前缀**由 BFF 据已认证会话的企业设置/解析**,前端永不发也永不见(BFF 列表时**剥前缀**只回 description 首行的展示名)。⇒ 用户无法伪造归属(BFF 是唯一写入/过滤点,omnigent 不可直达)。
  - (备选,延后:fork 加 `agent_labels` 表 + AgentObject 返回 labels;或 BFF 文件映射。MVP 用名字前缀最小、BFF 无状态。)
- **会话↔智能体**:omnigent 建会话绑定 `agent_id` 不可变;**"开始后锁定" = BFF 不暴露 `switch-agent`/`PUT .../agent`**。

### 我们不新增持久实体
- 无新 PG(§6.2)、无新 secret(§5.2);企业归属寄生在 omnigent agent name 前缀里,BFF 无状态。

## 核心流程

### 流程 A:管理员建智能体
1. 前端(管理员)提交 `{name, template(harness), model?, instructions?}`。
2. BFF:① 解会话 → `ctx` + 企业 alias;② **`can(ctx, "agent:create", Resource(kind="agent", enterprise_id=alias, owner=None))`**,拒则 403。
3. BFF 搭 **bundle**(`config.yaml`:`spec_version` + `name="<alias>_<ascii-id>"`(仅企业归属 + ASCII id)+ `description`(首行=展示名,空行后=用户描述)+ `executor.harness=<template>` + `instructions?` + `llm.model?`)→ multipart `POST omnigent /v1/agents`。
4. omnigent 注册可复用模板 → 返回 `agent_id`。
5. BFF 写**审计**(`agent:create`,actor/企业/agent_id)→ 回前端(展示名剥前缀)。

### 流程 B:列智能体(按企业)
1. 前端 `GET /v1/ws/agents`。
2. BFF:`GET omnigent /v1/agents` 全量 → **过滤**:保留「无前缀(内置)」+「前缀==调用者企业」;**剥前缀**后回展示名 + harness。

### 流程 C:对话开始选 + 锁定
1. 前端新会话前展示库(流程 B 的列表)→ 用户选 `agent_id`。
2. 前端 `POST /v1/ws/sessions {agent_id}`。
3. BFF **校验**:该 `agent_id` 是内置 或 其前缀==调用者企业,否则拒(防猜他企业 agent_id)→ 通过则 JSON `{agent_id, host_type:managed}` 建会话(9a 路径,全局共享订阅)。
4. 会话绑定该 agent 不可变;BFF 不提供换 agent 入口。

## 授权与安全
- **授权经 `can()`(§2.4)**:扩 `libs/authz/engine.py` 加一条——`action ∈ {agent:create, agent:configure, agent:delete}` 要求**该企业 enterprise-admin**(类比现有 `job.submit gpu>4` 规则);`agent:use`/列表 = 企业成员(can() 默认隔离即可)。**不**用散落角色判断(虽 invite 现为 ad-hoc,新代码走 can())。
- **隔离不变式(红线 = 负向测试)**:① 列表只含内置 + 本企业 ② 建会话校验 agent 归属、跨企业 agent_id 被拒 ③ 非管理员建/改 → 403(服务端,不靠前端藏按钮)④ omnigent 不可被前端直达 ⑤ `switch-agent` 不反代(锁定)。
- **secret(§5.2)**:无 per-agent 凭据;全局共享订阅沿用 9a(`secrets/omnigent.token`,gitignored)。
- **审计(§6.1)**:create/configure/delete 经 `libs/audit/oss_audit.py` 写 OSS append-only。
- **CSRF**:变更经 BFF 现有双提交(`X-CSRF-Token`)。

## 非功能(NFR)
- **parity(§5.3)**:`POST /v1/agents` 进 fork → `omnigent_build.sh dev` 自编译 → dev/prod 同源;bump submodule。
- **隔离**:企业过滤 + 建会话校验在 BFF;omnigent 租户无关。
- **无状态 BFF**:企业归属寄生 omnigent agent name,BFF 不新增持久存储。
- **可用性**:本版只有注入了凭据的 harness(claude 订阅)真能跑;库的"基底模板"先限可用的(claude-native 系),其余标注/隐藏(避免建出来不可用)。

## 依赖与引用
- **决策**:[ADR-027](../../../adr/ADR-027-agent-library.md)(本功能);承接 [ADR-026](../../../adr/ADR-026-omnigent-integration.md)、[ADR-025](../../../adr/ADR-025-keycloak-organizations-as-enterprise.md)。
- **探针事实**:[spikes/agent-create.md](./spikes/agent-create.md)——omnigent 无运行时建 agent 端点(实测 405)、AgentObject 无标签字段、`_ensure_builtin_agent` 可复用、`switch-agent` 存在(不反代即锁)。
- **复用(不复制)**:`can()`(`libs/authz/engine.py`)、审计(`libs/audit/oss_audit.py`)、enterprise-admin 解析(`libs/identity/context.py` `role_in`)、BFF 反代骨架(`services/gateway/bff/omnigent_proxy.py`)、前端 list+create(`frontend/src/pages/Datasets.tsx`+`UploadModal.tsx`)、角色(`frontend/src/auth/useOrgs.ts`)。

## 技术选型理由
- **名字前缀编码企业(非 fork 加 labels 表)**:MVP 最小、BFF 无状态、合 §1.5;labels 表/BFF 映射作后续可选硬化。
- **小 fork `POST /v1/agents`(非 BFF 每会话现搭 bundle)**:后者要 multipart 建会话支持 managed(未证、很可能也要 fork),且每会话重建 agent 浪费;暴露已有内部函数更干净、可 upstream。
- **`can()` 扩规则(非 ad-hoc 角色判断)**:合 §2.4 唯一出入口。

## ★ DoR 自检(逐项三态)
- [x] **1 范围与出口**:**已决定**。In=库页+建(admin)+对话选+锁+每企业隔离;Out/推迟=per-agent 凭据/vault/多 provider/编辑内置/共享授予。可证伪=spec SC + 隔离负向。
- [ ] **2 接口契约**:**部分待 plan 细化**。对外=智能体库 UI(第一个消费者=该页,仿 Datasets 低保真已有)。BFF↔omnigent:`POST /v1/agents`(bundle 格式)、`GET /v1/agents`、JSON managed 建会话——**探针已钉死端点**;**bundle 最小可用格式 + BFF 搭 bundle 建出能跑的 claude-native 自定义 agent,Task A 首步 live 验证**(续探针)。错误形态:非 admin 403、跨企业拒、重名提示、不可用 harness 明确报。
- [x] **3 数据模型**:**已决定**。企业归属=omnigent agent name 前缀 `"<alias>_<ascii-id>"`(SEP=`_`,因 omnigent name 仅许 `^[a-zA-Z0-9_-]+$`;BFF 写/解/剥);人类展示名落 `description` 首行;内置=无前缀=全局;**alias 必须 `_`-free**(guard 强制)；不变量见上;不新增 PG。
- [x] **4 外部依赖事实**:**已实测**(spikes/agent-create.md):omnigent 无建 agent 端点(405)、`_ensure_builtin_agent` 可暴露、AgentObject 字段、switch-agent 存在。**决策=小 fork POST /v1/agents**(owner 已拍)。
- [x] **5 行为·边界·并发·威胁**:**已决定**。边界(建会话失败/重名/进行中换/不可用 harness/非 admin 直调/未登录)见 spec Edge Cases;红线=隔离负向 + 锁定。
- [x] **6 NFR**:**已决定**。parity(fork 自编译)、隔离(BFF 过滤+校验)、无状态 BFF、无新 secret、可用 harness 限制。
- [ ] **7 验收与测试策略**:**plan 产出 runbook**。可证伪=SC + 双企业隔离负向;测试分层=BFF 单元(MockTransport:非admin403/跨企业/打标签/建会话校验)、前端 vitest、手动 runbook(admin 建→同企业用→跨企业不可见→非admin403)。
- [x] **8 关键决策留痕**:**ADR-027**(小 fork POST /v1/agents、名字前缀编码企业、can() 扩 agent 规则、全局共享订阅无 per-agent 凭据、switch-agent 不反代锁定;否决 BFF每会话bundle/agent_labels表/built-ins-only)。

> **DoR 结论**:8 项中 6 已决定;#2(bundle 最小格式 live 验证)= Task A 首步续探针、有决策规则;#7(runbook)= plan 产出。无静默 TBD。**进 writing-plans 前需 owner 过门 + ADR-027 落定。**
