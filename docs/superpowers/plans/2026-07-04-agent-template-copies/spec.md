# Spec(需求):企业默认智能体模板(Default Enterprise Agents)

> 需求层(WHAT/WHY)。实现细节见 [`design.md`](./design.md),执行步骤见 [`../2026-07-04-agent-template-copies.md`](../2026-07-04-agent-template-copies.md)。
> **状态**:Draft · **输入**:owner 2026-07-05 —— "每个企业在创建的时候有默认的智能体,包括 minimax、debby、codex 和 polly,企业管理员可以编辑。fork 的实现方式太重了,只需要企业创建的时候有一个模版就好。"
> **关联**:承接 [ADR-027](../../../adr/ADR-027-agent-library.md)(智能体库)、Plan 9a omnigent 集成。遵循 constitution §1(企业隔离)、§2.4(can())、§5.2(secret)、§6.1(审计)。

## Goal & 价值
- **目标**:每个企业在创建/置备完成时自动拥有 4 个默认的**本企业智能体**:`minimax`、`debby`、`codex`、`polly`。这些智能体从一组 Lite AI 维护的默认模板定义生成,不是从 omnigent 内置模板做运行时 clone。
- **价值**:企业一创建就能直接使用常用智能体,管理员看到的都是"本企业"资源,可以编辑/删除;同时去掉 fork 新增 `copy` 端点、全量复制内置模板、首次进库延迟种子等重方案。
- **成功长这样**:新企业创建后,管理员打开智能体库,默认看到 4 个本企业智能体: minimax、debby、codex、polly。管理员可以编辑/删除任一默认智能体;普通成员可以使用但不能编辑/删除。平台内置模板可以继续存在于 omnigent,但企业侧列表不显示它们。

## 范围
- **In(本版做)**:
  - 定义 4 个默认企业模板:
    - `minimax`: harness=`openai-agents`, model=`MiniMax-Text-01`(默认,可编辑),说明为 OpenAI 兼容 provider 模板。
    - `debby`: harness=`claude-sdk`,面向多视角讨论/审查的助手模板。
    - `codex`: harness=`codex`,面向代码实现/修改的助手模板。
    - `polly`: harness=`claude-sdk`,面向拆解任务、分派子任务、协调实现的助手模板。
  - 在**企业创建/置备流程**中为该企业创建上述默认智能体,归属编码为本企业 alias。
  - 默认智能体是普通本企业 agent:企业管理员可编辑/删除;成员只可查看/使用。
  - 智能体库企业侧列表只展示本企业 agent,不再展示 omnigent 内置模板,避免同名默认副本与只读内置模板并列。
  - 过程必须幂等:同一企业重复置备不会重复创建同名默认智能体。
  - 兼容已有企业:提供一次性/幂等的补种入口,用于 dev `ent-demo` 或线上已有企业。
- **Out / 推迟(vN+)**:
  - 不做 omnigent fork `POST /v1/agents/{id}/copy`。
  - 不复制 omnigent 全部内置模板;本版只创建 4 个明确模板。
  - 不要求忠实复制 debby/polly 上游 bundle 的 skills/mcp/capability。默认模板以本项目定义的 `name / description / instructions / harness / model` 为准。
  - 不做"删除后恢复默认模板"入口。
  - 不做平台管理员在线管理默认模板 UI。
  - 不引入 per-agent 密钥/vault;凭据继续走企业模型配置或平台默认。

## User Scenarios & Testing

### User Story 1 — 新企业创建时获得 4 个默认智能体 (P1)
企业创建/置备完成后,系统自动为该企业创建 minimax、debby、codex、polly 四个本企业智能体。

- **可独立测试**:对一个无本企业智能体的新企业运行企业置备/默认智能体初始化 → 再列智能体 → 返回 4 个 `enterprise_owned=true` 的智能体。
- **验收**:
  1. **Given** 企业 `ent-new` 刚创建且没有本企业 agent **When** 初始化默认智能体 **Then** 创建 minimax、debby、codex、polly 四个本企业 agent。
  2. **Given** 默认智能体创建完成 **When** 管理员打开智能体库 **Then** 四个默认智能体都显示为"本企业",没有"内置只读"限制。
  3. **Given** 默认智能体已存在 **When** 再次运行初始化 **Then** 不重复创建第二份 minimax/debby/codex/polly。

### User Story 2 — 企业管理员可编辑/删除默认智能体 (P1)
默认智能体与企业自己新建的智能体一样,由企业管理员管理。

- **可独立测试**:管理员编辑 debby 的提示词并保存,删除 polly,列表更新;普通成员直调编辑/删除接口被拒。
- **验收**:
  1. **Given** 管理员编辑默认智能体 **When** 保存 **Then** 保存成功,改动只影响本企业。
  2. **Given** 管理员删除默认智能体 **When** 刷新列表 **Then** 该智能体从本企业列表消失。
  3. **Given** 普通成员尝试编辑/删除 **When** 调接口 **Then** 返回 403,不打到 omnigent 写路径。

### User Story 3 — 跨企业隔离 (P1)
每个企业各有自己的默认智能体副本;一个企业修改/删除不影响另一个企业。

- **可独立测试**:分别初始化企业 A/B → A 编辑 minimax、删除 polly → B 的 4 个默认智能体仍不变。
- **验收**:
  1. **Given** A/B 都已初始化默认智能体 **When** A 修改或删除其中一个 **Then** B 的同名默认智能体不变。
  2. **Given** B 用户拿 A 的 agent_id 建会话 **When** 调建会话接口 **Then** 被拒,不能跨企业使用。

### User Story 4 — 已有企业可补种且不重复 (P2)
上线前已存在的企业可以运行补种,只补缺失的默认智能体,不覆盖已有同名企业 agent。

- **可独立测试**:企业已有 `debby` 本企业 agent,缺 minimax/codex/polly → 补种后只新增缺失 3 个,原 debby 不被覆盖。
- **验收**:
  1. **Given** 企业已存在某些默认名 agent **When** 运行补种 **Then** 只创建缺失项。
  2. **Given** 企业管理员已改过默认智能体 **When** 再运行补种 **Then** 不覆盖管理员修改。

## Edge Cases
- 企业创建成功但 omnigent 暂不可达:初始化应失败显式返回/记录,不得伪装企业全量就绪;置备命令可重试。
- 默认模板创建到一半失败:重复运行应补齐缺失模板,不会重复已创建模板。
- 企业删掉某默认智能体:再次运行普通企业创建流程不会自动复活;只有显式补种命令/操作才补缺失。
- minimax 需要企业配置 OpenAI 兼容 provider 凭据和模型名才能真正对话;创建模板本身不写密钥。
- codex harness 当前依赖 ChatGPT/Codex 订阅态;模板可创建,运行可用性由后续模型/订阅配置决定。

## Success Criteria
- **SC-001**:新企业初始化后,本企业智能体列表含且仅含 4 个默认模板名: minimax、debby、codex、polly(不计管理员后续自建项)。
- **SC-002**:重复初始化同一企业不会产生重复默认智能体。
- **SC-003**:管理员可编辑/删除任一默认智能体,普通成员编辑/删除被拒。
- **SC-004**:企业 A 修改/删除默认智能体后,企业 B 的默认智能体不变且不可被 A/B 互相访问。
- **SC-005**:默认初始化不需要新增 omnigent fork 端点,只复用现有 `POST /v1/agents` 与 BFF bundle 生成能力。

## Assumptions
- 企业创建/置备入口可以调用一个幂等的默认智能体初始化函数或脚本;dev 先挂到 `scripts/provision_orgs.py` 之后的工作流/新脚本,生产企业创建服务接同一能力。
- 默认模板定义由 Lite AI 在代码中维护,作为受控产品默认值,不是用户输入。
- 默认智能体凭据不随 agent 保存;继续使用 `ModelConfig` 按企业注入 provider 凭据。
- 企业侧列表隐藏 omnigent 内置模板;平台内置模板只作为 omnigent 自身保留对象,不作为企业用户可操作对象。

## Spec 质量自检
- [x] 已按 owner 新要求移除 fork clone、全量平台模板复制、首次进库种子。
- [x] 用户故事均有优先级、可独立测试、Given/When/Then 验收。
- [x] Success Criteria 可测且与现有 BFF/omnigent 能力一致。
- [x] 未引入 per-agent 凭据、跨企业共享、散落授权判断等宪法违例。
