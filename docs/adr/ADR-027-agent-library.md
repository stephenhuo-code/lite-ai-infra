# ADR-027: 智能体库(Agent Library)—— 每企业一套 + 全局共享订阅 + 小 fork 暴露建 agent

- 状态:**Proposed(2026-06-30)**。owner 已拍定方向(option A 小 fork);正式 Accept 留待 DoR 过门 + Task A 首步 live 验证(BFF 搭 bundle 建出能跑的自定义 claude-native agent)。
- 决策人:owner
- 关联:承接 [ADR-026](./ADR-026-omnigent-integration.md)(omnigent 集成,9a)、[ADR-025](./ADR-025-keycloak-organizations-as-enterprise.md)(企业=KC Org)。遵循 constitution §1(隔离)、§2.4(can())、§5.2(secret)、§5.3(parity)、§6.1(审计)。spec/design:[`2026-06-30-agent-library/`](../superpowers/plans/2026-06-30-agent-library/)。探针:[spikes/agent-create.md](../superpowers/plans/2026-06-30-agent-library/spikes/agent-create.md)。

> **背景**:9a 把 omnigent 当"通用对话"集成进来(单一内置 claude-native + 全局共享订阅)。owner 要升级成"智能体库":展示智能体、**企业管理员**可建自定义智能体(名字/模板/模型/提示词)、对话开始选、开始后锁。探针实测:**omnigent 故意无运行时建 agent 端点**,且 agent 全局无租户字段。

## Decision

### 1. 小 fork:`POST /v1/agents`(暴露 omnigent 自身已有逻辑)
- omnigent 内部 `_ensure_builtin_agent(...)`(启动期 seed 内置模板用)已完整,但**无 HTTP 入口**(`POST /v1/agents` 实测 405)。
- fork 在 `omnigent/server/routes/builtin_agents.py` 加 `@router.post("/agents")`:收 multipart bundle → 校验 spec → 调 `_ensure_builtin_agent` → 返回 `AgentObject`。**纯加法、复用现成函数、不碰内部接线、可 upstream**。提交进我们 fork(模型 C)→ `omnigent_build.sh dev` 重编译 → bump submodule。
- 端点走 omnigent 现有 header-auth;**"谁能建"的把关在 BFF**(omnigent 租户/角色无关)。

### 2. 企业归属:BFF 在 omnigent agent name 编结构化前缀
- AgentObject 无 labels/metadata 字段(探针实测)。**BFF 创建时把 enterprise alias 编进 agent `name`** 作前缀;**无前缀 = 内置模板 = 全局共享**。
- **name 编码(as-built)**:SEP = ASCII 下划线 **`_`**,`name = "<alias>_<ascii-id>"` —— name 只承载【企业归属】+ 一个 ASCII id。**人类展示名(任意 Unicode)落 `description`**(首行=展示名,空行后=用户描述,读时拆回)。
- **不变量:enterprise alias 必须 `_`-free**(`^[a-zA-Z0-9-]+$`)—— 否则 `name.partition("_")[0]` 会错切前缀、可能跨企业泄漏(违 §1)。由 BFF `_resolve_ctx` 的 guard 强制(alias 不符 → 409 `enterprise alias incompatible with agent library`),覆盖 create/list/session-create。内置名(`*-native-ui` 等)用连字符不含 `_` → 不误判成某企业所有。
- 前缀由 **BFF 据已认证会话设置/解析/剥离**,前端永不发也永不见 → 用户无法伪造归属(BFF 唯一写入+过滤点,omnigent 不可直达)。符合 §1.5"归属编码在资源自身"。
- 备选(延后):fork 加 `agent_labels` 表 + AgentObject 返回 labels;或 BFF 文件映射。

> **实现修订(2026-06-30)**:原 ADR 写 SEP=`␟`(U+001F)且把显示名编进 name(`<alias>␟<显示名>`)。Task A live 验证发现 omnigent 的 name 校验器 = `^[a-zA-Z0-9_-]+$`(仅 ASCII 字母数字+`_`+`-`):`␟` 是控制符会被 400 拒,中文展示名也根本进不了 name。故改为 **SEP=`_` + `name="<alias>_<ascii-id>"` + 展示名落 `description`**,并新增 **alias `_`-free guard**(`_`-分隔归属还原的正确性前提)。隔离/授权逻辑不变,仅归属编码载体与分隔符随实测约束修订。

### 3. 授权:扩 `can()` 加 agent 规则(§2.4)
- `libs/authz/engine.py` 加一条:`action ∈ {agent:create, agent:configure, agent:delete}` 要求该企业 **enterprise-admin**(类比已有 `job.submit gpu>4` 规则);`agent:use`/列表 = 企业成员(can() 默认隔离)。新代码经 `can()`,不散落角色判断。

### 4. 凭据(初版):一律全局共享订阅 → **增量(2026-07-01)部分推翻,见 §4'**
- 初版智能体**只差模板/模型/提示词/名字**;**全用平台全局共享订阅**(9a 的 `CLAUDE_CODE_OAUTH_TOKEN`),不引入 per-agent 凭据。
- ~~故库的"基底模板"先限 claude-native~~ —— 见 §4'。

### 4'. 增量(2026-07-01,owner 拍板"按推荐"):per-agent **API key** + 编辑
> owner 要"给每个智能体设 harness + apikey/订阅"。本增量做 **per-agent API key + 编辑本企业 agent**;**per-agent 订阅仍推迟**(omnigent native 只认全局 token,要更大 fork)。
- **per-agent API key 走 omnigent 原生 `executor.auth`**(SDK harness:claude-sdk/codex/qwen/pi… 读它)。管理员在建/编辑表单填 harness + api_key(+ base_url),BFF 写进 bundle 的 `executor.auth`。**claude-native 仍用全局共享订阅**(它不读 executor.auth);**per-agent 订阅 token 不做**(推迟)。
- **安全:fork 白名单"安全放开" executor.auth**。当初无条件拒 executor.auth 是为堵"HTTP 上传的 built-in 在 `expand_env=True` 下把 `${服务器密钥}` 展开外泄"(Critical,见 §2 探针/审查)。放开方式:**允许 executor.auth/connection 的字面值,但仍用 `_contains_env_ref` 扫描拦掉任何 `${}`/`$VAR` 引用** —— 字面 key(`sk-...`)无 `${}` → expand_env 不展开任何东西 → 安全;`${SERVER_SECRET}` 仍被拒 → 外泄面不变。mcp_servers / 能力位(spawn/timers/…)仍**拒**(不在本增量需求内)。
- **凭据存哪**:进 omnigent 的 agent bundle(其 postgres,明文)——满足 owner"不进 git";**生产再上 KMS**(推迟)。**仍无我们自己的 secret store**。
- **编辑** = 复用幂等 `POST /v1/agents`(按 name upsert):BFF 新 `PUT /v1/ws/agents/{id}` → can(`agent:configure`)+ 本企业 own 校验 → 查该 agent 的 omnigent name → 用新字段重搭 bundle、**同名 re-POST**(omnigent bump version)。内置模板(全局)**不可编辑**(改了影响所有企业)。
- 可用性:配了有效 key 的 SDK agent 真能跑;claude-native 用全局订阅;其它 harness 没配 key 则建不出/标不可用。

### 5. "对话开始后不能改" = BFF 不反代 switch-agent
- omnigent 原生有 `POST /v1/sessions/{id}/switch-agent`、`PUT .../agent`(允许会话内换 agent)。**BFF 不暴露这两个端点** ⇒ 默认锁定,零成本。

### 6. 增量(2026-07-05):企业创建时默认智能体模板
- 新企业创建/置备时默认获得 4 个本企业 agent:minimax、debby、codex、polly。
- 默认 agent 由 Lite AI BFF 维护的模板定义生成,复用现有 `POST /v1/agents`;不新增 omnigent fork clone 端点。
- 默认 agent 是普通本企业资源,企业管理员可编辑/删除;普通成员不可改删。
- 凭据不进入 agent bundle,继续由企业模型配置/平台默认注入。

## Consequences
**正面**:满足"建自定义智能体 + 每企业隔离 + admin-only + 对话选/锁";fork 极小(暴露已有函数)、可 upstream;企业隔离/授权/审计全在 BFF,omnigent 保持租户无关;无新 secret、无新 PG、BFF 无状态。

**负面/风险**:① 多一个 fork 点(model C 维护成本,但小)② 企业归属寄生 name 前缀(约定式,若 omnigent 改 name 语义需跟进;labels 表是更干净的后续硬化)③ 只有注入凭据的 harness 真能跑(库要限可用模板,否则建出来不可用)④ 无 per-agent 凭据(企业不能各用各的订阅——本版有意推迟)。

## 否决的备选
- **不 fork、只展示内置 11 模板**:管理员不能建自定义——不满足 owner"创建智能体"。
- **不 fork、BFF 每会话现搭 bundle 走 multipart 建会话**:multipart 建会话是否支持 managed 隔离未证(很可能也要 fork),且每会话重建 agent 浪费。
- **fork 加 `agent_labels` 表**:更干净但更大(DB 迁移);MVP 用 name 前缀,labels 表留后续。
- **per-agent 凭据 / secret vault 本版就做**:地基工程(KMS/Vault),ADR-026 已推迟;owner 定"先全局共享订阅,生产再议"。
- **ad-hoc 角色判断(照 invite)**:违 §2.4;新代码走 `can()`。

## 探针结论(2026-06-30,已实测)
- `POST/PUT /v1/agents` → **405**(omnigent 故意无运行时建 agent);`GET /v1/agents` 返回 11 内置模板,字段无 labels/metadata(仅 name/description/harness 可用)。
- `_ensure_builtin_agent` 可复用暴露;`switch-agent` 存在(不反代即锁)。详见 spike。
- **决策**:采纳 option A(小 fork)。owner 研判探针后铺开 Phase 1+。
