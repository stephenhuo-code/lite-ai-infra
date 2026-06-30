# 探针:omnigent 运行时建可复用 agent 契约(智能体库 Phase 0)

**日期**:2026-06-30　**结论**:❌ **omnigent 无运行时"建可复用 agent"端点(设计如此)→ 需小 fork**。owner 研判后定方向。

## 实测到的(源码 + 真服务)

- **`GET /v1/agents`**(`server/routes/builtin_agents.py:133`)只读;返回 11 个内置模板。每个 agent 返回字段:`id, object, name, description, version, created_at, updated_at, harness, mcp_servers, mcp_servers_editable, policies, skills, terminals`。**无 labels/metadata/params 字段**——能承载企业标签的只有字符串 `name`/`description`。
- **`POST /v1/agents` → 405、`PUT /v1/agents` → 405**(真服务实测)。omnigent **故意不提供** agent 的 create/update/delete:`builtin_agents.py` 文档串原话 *"there is intentionally no create/update/delete — agent writes happen through session creation"*。
- **可复用模板 agent(session_id NULL)只在 server 启动时 seed**:CLI `omnigent server --agent <path>`、env `OMNIGENT_BUILTIN_AGENT_DIRS`(启动期、不热加载)、内部 `_ensure_default_agents()`/`_ensure_builtin_agent()`(`server/app.py:301-476`)。
- **`POST /v1/sessions` multipart(metadata + bundle.tar.gz)** 建的是**会话内 agent(session_id NOT NULL)**,不是可复用库模板(`sessions.py:13122`;"Each upload creates a session-scoped agent row")。其 `SessionCreateMetadata` 字段:`title/labels/reasoning_effort/host_id/workspace/terminal_launch_args/parent_session_id`——**未见 host_type**(managed 与否需另验;现有 managed 走 JSON `{agent_id,host_type:managed}` 路径,需要 pre-existing agent_id)。
- **agent spec 字段**(`spec/types.py:1373`):`name/description/instructions(系统提示词)/llm(模型)/executor(harness,如 claude-native)/params/skills/mcp_servers/...`。最小自定义 = 基底模板 + 改 name + instructions + (可选)model。
- **"建后锁"零成本但要主动锁**:omnigent **有** `POST /v1/sessions/{id}/switch-agent`、`PUT /v1/sessions/{id}/agent`——即它**允许**会话内换 agent。要满足"对话开始后不能改",**BFF 不反代这两个端点**即可(默认锁)。

## 钉死的事实

1. 要"运行时建自定义可复用 agent",**omnigent 必须改**(无现成端点)。
2. 内置 seed 用的内部函数 `_ensure_builtin_agent(agent_store, artifact_store, agent_cache, name, bundle_bytes)` **已完整**(启动期就在用),把它包成一个 HTTP 端点是最小改动(~50-100 行,低风险,甚至可 upstream)。
3. AgentObject 无标签字段;企业归属若不想污染 omnigent,可由 **BFF 自己维护 agent_id→enterprise 映射**(文件存储,仿 `raw_store.py`),omnigent 保持租户无关。

## 决策选项(报 owner)

- **(A) 小 fork:加 `POST /v1/agents`**(暴露已有的 `_ensure_builtin_agent`)。BFF 调它建自定义模板 → 拿 agent_id → 在 BFF 侧记 agent_id→enterprise(文件映射)+ audit;list 用 `GET /v1/agents` 全量按映射过滤;建会话沿用 JSON managed `{agent_id,host_type:managed}`。**满足全部需求**;fork 小且干净。**← 推荐**
- **(B) 不 fork:库只展示 11 个内置模板**,不支持自定义创建(砍掉"创建智能体"需求)。最快,但不满足 owner 要的"建智能体"。
- **(C) 不 fork、BFF 侧库 + 每会话从 bundle 建**:库存我们这,对话开始时 BFF 现搭 bundle 走 multipart `POST /v1/sessions`。**风险**:multipart 路径是否支持 **managed host** 未证(metadata 无 host_type);若不支持,仍要 fork(给 multipart 加 managed)→ 退回需 fork。

## 结论

**采纳 (A) 小 fork `POST /v1/agents`**(待 owner 确认)。它是暴露 omnigent 自己启动期就在用的内部函数,非"私改内部接线",符合模型 C fork 维护;企业隔离仍全在 BFF(agent_id→enterprise 映射),omnigent 租户无关。owner 拍板后进 Phase 1(spec/design/ADR-027)。
