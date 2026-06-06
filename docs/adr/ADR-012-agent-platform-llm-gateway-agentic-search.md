# ADR-012: Agent 平台 + 统一 LLM 接入（LLM Gateway）+ Agentic Search

- 状态：Accepted（2026-06-06 更新：spike① 已结 → **接入模型由"订阅"改为 API key 按 token 计费**；LiteLLM 实测等剩余 spike 见行动项）
- 日期：2026-06-06
- 决策人：平台团队（P1/P2/P3）
- 相关：design §0 / §1.1 架构图（AI 应用平面）/ §1.2（⑮⑯⑰）/ §2.2 版本路线（v2/v3）/ §5 发布计划 / ADR-010（多企业）/ ADR-011（Cerbos 授权）

---

## Context

战略调整：平台向 **Agent + 第三方 LLM 应用** 倾斜，**先用现成大模型快速交付应用价值，自研微调/预训练后置**。版本路线扩为：

```
v1 数据域 → v2 Agent 平台 + 统一 LLM 接入 → v3 Agentic Search → v4 微调 → v5 1B 预训练
```

由此引入三个新子系统（design §1.1 AI 应用平面）：

- **⑮ 统一 LLM 接入服务（LLM Gateway）**
- **⑯ Agent 平台 + 统一对话交互**
- **⑰ Agentic Search**

需求要点：

- 统一接入 **Claude / OpenAI / Minimax 等第三方模型**（**经各家 API key、按 token 计费**；也含未来自托管模型）。
- 内置 agent 辅助 **模型开发 / 管线开发 / 数据探查**。
- 一个 agent 对**多源多模态数据**统一检索（v3）。
- 全程按 **enterprise/group** 隔离 + 计量 + 授权。

---

## Decision

### 1. 统一 LLM 接入服务（LLM Gateway，⑮，v2）

- **唯一出口**：所有 chat/completion/embedding 调用都经 Gateway，业务/agent **不直连**任一模型厂商。
- 能力：**模型路由**（按名称/能力/成本）、**API key 管理**、**限流**、**按 enterprise/group token 计量**、**回退/重试**、统一可观测。
- 选型：**LiteLLM 为首选候选**（多 provider + API key + 计量，契合需求；spike① 已验，见行动项）。
- 接入目标：**Claude（Anthropic API）/ OpenAI API / Minimax API**，**统一 API key、按 token 计费**；新增模型 = 加一条 Gateway 配置，业务零改。
- **⚠️ 不用消费订阅**（Claude Pro/Max、ChatGPT Plus）：其消费 ToS 禁止程序化/多租户使用，且 LiteLLM 按 API key 工作。订阅仅供**团队内部开发工具**（Claude Code / Codex CLI），不进产品路径。
- 授权：调用经 `PolicyEngine.can()`（Cerbos，ADR-011）——按 enterprise/group + 模型/配额 scope 受控。

### 2. Agent 平台 + 统一对话交互（⑯，v2）

- **Agent 框架 + 运行时 + 统一 chat UI**（前端统一对话入口 + 会话/任务管理）。
- 内置 agent：**模型开发 / 管线开发 / 数据探查**，复用第三方模型（经 Gateway）。
- **工具调用走 Platform API 契约**（API 优先，§3.0）——agent 通过受治理的工具访问数据/作业/元数据，不绕过授权。
- agent 的数据/资源访问同样经 Cerbos + 数据层 scope 过滤。

### 3. Agentic Search（⑰，v3）

- **一个 agent 对集成的多源多模态数据**（OSS 对象 / Lance 向量 / Gravitino 元数据 / MLflow 实验…）做**统一检索**。
- 流程：**查询规划 → 多模态检索（结构化 + 向量 + 全文）→ 综合 → 带引用返回**。
- 复用 **v1 数据/向量 + v2 LLM Gateway**；结果**严格限定当前 enterprise/group scope**（数据层过滤 + Cerbos）。

### 4. 隔离与计量

- 所有 LLM/agent/search 访问按 enterprise/group 授权与计量（v1 起薄 can()，v2 起 Cerbos 细粒度）。
- LLM 用量计量为 vN+ 计费（PG 账本回归）打基础；v2 先做用量统计（落 OSS/日志或轻量表）。

### 5. 可用性

- **LLM Gateway 是 v2 起的关键路径**（agent/对话/检索都依赖它）→ 多副本、无状态、上游厂商故障时回退。

---

## Consequences

### 正面
- 用第三方大模型**快速交付应用价值**，绕开自研训练的长周期；自研微调/预训练后置（v4/v5）。
- Gateway 统一出口 → 模型可插拔、成本/密钥集中治理、按租户计量、便于合规审计。
- Agent 工具走 Platform API 契约 → 能力受治理、可授权、可观测。

### 负面 / 代价
- 引入**外部依赖与按 token 成本**（厂商可用性、限流、计费）；Gateway 成关键路径需 HA。
- **成本模型 = API 按 token 计费**（非订阅，见 spike① 结论）→ 需明确 LLM 成本如何计费给客户 / 平台承担。
- Agent/Agentic Search 是较大的自研工作量 → 时间线延长（见 §5）。

### 风险登记

| 风险 | 缓解 |
|---|---|
| ~~订阅式程序化接入受 ToS 限制~~（spike① 已结，见行动项）| **结论：不可用消费订阅 → 改 API key 按 token 计费**（合规）|
| LiteLLM 不满足（多厂商 / 计量）| 藏在 Gateway 接口后可替换（备选 OpenRouter / 自研薄 Gateway）|
| LLM 成本失控 | Gateway 限流 + 按 enterprise/group token 计量（v2 必做）+ 硬配额（vN+）|
| agent 越权访问数据 | 工具走 Platform API + Cerbos；检索结果 scope 过滤（继承调用者 scope）|

---

## 行动项

- ✅ **spike①（订阅 ToS / 接入可行性，2026-06-06 已结）**：**结论 NO-GO 订阅、GO API key 按 token 计费**。依据：Anthropic 消费 ToS 禁止程序化访问（除 API key / Claude Code）、Agent SDK 强制 API key；OpenAI ChatGPT Plus 不可程序化、Codex+订阅仅限个人；LiteLLM 按 API key 工作。→ 已更新本 ADR 接入模型为 **API key 计费**；订阅仅供团队内部开发工具。
- **剩余 spike（v2 前）**：① LiteLLM 多厂商路由 + 按租户计量/限流 + Python 集成实测；② 各家 API key 申请/配额/单价确认（成本模型）。
- v3 Agentic Search 检索策略（向量 + 全文 + 元数据融合）单独设计 spike。
