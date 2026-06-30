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
- AgentObject 无 labels/metadata 字段(探针实测)。**BFF 创建时把 enterprise alias 编进 agent `name`** 作前缀(`<alias>␟<显示名>`);**无前缀 = 内置模板 = 全局共享**。
- 前缀由 **BFF 据已认证会话设置/解析/剥离**,前端永不发也永不见 → 用户无法伪造归属(BFF 唯一写入+过滤点,omnigent 不可直达)。符合 §1.5"归属编码在资源自身"。
- 备选(延后):fork 加 `agent_labels` 表 + AgentObject 返回 labels;或 BFF 文件映射。

### 3. 授权:扩 `can()` 加 agent 规则(§2.4)
- `libs/authz/engine.py` 加一条:`action ∈ {agent:create, agent:configure, agent:delete}` 要求该企业 **enterprise-admin**(类比已有 `job.submit gpu>4` 规则);`agent:use`/列表 = 企业成员(can() 默认隔离)。新代码经 `can()`,不散落角色判断。

### 4. 凭据:一律全局共享订阅(无 per-agent 凭据)
- 本版智能体**只差模板/模型/提示词/名字**;**全用平台全局共享订阅**(9a 的 `CLAUDE_CODE_OAUTH_TOKEN`)。**不引入 per-agent 凭据 / secret vault**。
- 故库的"基底模板"先限**已注入凭据的 harness**(claude-native 系);codex/openai 等需全局注入对应凭据才可用(可选扩展,本版不做)。

### 5. "对话开始后不能改" = BFF 不反代 switch-agent
- omnigent 原生有 `POST /v1/sessions/{id}/switch-agent`、`PUT .../agent`(允许会话内换 agent)。**BFF 不暴露这两个端点** ⇒ 默认锁定,零成本。

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
