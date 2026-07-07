# Spec(需求):模型配置 provider 重整 + 每 provider 独立 harness

> 需求层(WHAT/WHY)。**禁**技术栈/契约 schema/实现(归 design.md / plan)。
> **状态**:Draft · **关联**:承接 ADR-028(每企业模型凭据注入,as-built 待补 ADR)、ADR-027(智能体库/默认 agent)、Plan 9a(omnigent 集成) · **输入**:owner ——「①Anthropic(Claude)和其他一样,是平台的一个普通模型,不是"默认",也可以改;claude 只保留 API key 模式,去掉订阅 token 模式。②去掉 Gemini,增加 MiniMax 和 DeepSeek。③MiniMax/DeepSeek 都用 openai harness,需要各复制一份 harness 改名、各读自己的凭据槽,能同时配置并用。」

## Goal & 价值
- **目标**:让企业管理员在「模型配置」页把 **Anthropic、OpenAI(Codex)、MiniMax、DeepSeek** 四个 provider 各自独立配置本企业凭据,互不冲突;新企业默认智能体覆盖 minimax、deepseek 两个新 provider。
- **价值**:① 去掉 Anthropic 的"平台默认"特殊态,让所有模型在配置页语义一致、可被企业自主管理 ② 让两个 OpenAI 兼容 provider(MiniMax/DeepSeek)能**同时**配置并各自可用,而不是互相覆盖 ③ 收敛凭据模型:claude 只走 API key,减少订阅/API 双态的认知与冲突面。
- **成功长这样**:企业管理员在一个页面里分别给 MiniMax、DeepSeek 填各自的 key+endpoint,两者都保存成功;对话里 minimax 默认 agent 用 MiniMax 凭据、deepseek 默认 agent 用 DeepSeek 凭据,同一企业内两者都能跑、互不串号;Anthropic 显示为普通"已配置/未配置",未配则 claude 类 agent 明确不可用(与其它 provider 完全一致)。

## 范围
- **In(本次做)**:
  - 「模型配置」页 provider 列表:**去 Gemini,增 MiniMax、DeepSeek**;Anthropic 去"平台默认"态、仅保留 API key;OpenAI(Codex)保留不动。
  - fork 侧:为 MiniMax、DeepSeek **各新增一个 harness**(复制 openai-agents 语义,各读自己的凭据槽 env),注册进 harness 表。
  - 每 provider 独立的沙箱注入 env 槽(MiniMax/DeepSeek 各一组,不再抢 `OPENAI_*`)。
  - 默认企业智能体:**由 4 个增为 5 个**(minimax、deepseek、debby、codex、polly);minimax 走 minimax harness、deepseek 走 deepseek harness。
  - 去掉 Anthropic 的**平台全局订阅 token 回退**(compose 不再全局注入 claude 订阅);claude 类 agent 改由企业配置的 `ANTHROPIC_API_KEY` 驱动。
  - 相应 ADR / runbook / 测试更新。
- **Out(本次不做)**:
  - 不动 OpenAI(Codex)provider 的凭据模型与 codex 默认 agent。
  - 不新增除 MiniMax/DeepSeek 外的 provider;不做 per-agent key(仍走每企业模型配置)。
  - 不改授权模型(仍 enterprise-admin 经 `can()`)、不改隔离命门(labels.enterprise_id 仍服务端据会话 alias 构造)。
- **推迟(vN+)**:模型用量计量/限流;provider 健康探活;凭据轮换。

## User Scenarios & Testing

### User Story 1 — 两个 OpenAI 兼容 provider 同时可用 (Priority: P1)
企业管理员分别给 MiniMax 和 DeepSeek 配置各自的 API key + endpoint,两者都保存成功;对话里 minimax 默认 agent 用 MiniMax、deepseek 默认 agent 用 DeepSeek,同一企业里两者都能回复、互不串号。

- **Why this priority**:这是本次的核心——解决"两个 OpenAI 兼容 provider 抢同一组 env、无法共存"的真实冲突。
- **可独立测试**:配 MiniMax + DeepSeek → 各起一个对应默认 agent 对话 → 两者都成功回复,后台看两者读的是不同凭据。
- **验收场景**:
  1. **Given** 管理员已配 MiniMax 和 DeepSeek **When** 查看配置页 **Then** 两个 provider 都显示"本企业已配置",互不影响。
  2. **Given** 两者都配好 **When** 分别用 minimax、deepseek 默认 agent 对话 **Then** 都能收到流式回复。
  3. **Given** 只配了 MiniMax、没配 DeepSeek **When** 用 deepseek agent 对话 **Then** 明确报该 provider 未配置/不可用,**不**误用 MiniMax 的 key。

### User Story 2 — Anthropic 是普通 provider (Priority: P1)
Anthropic 在配置页显示为普通"已配置/未配置",没有"平台默认"徽标;只提供 API key 一种凭据类型;未配置时 claude 类 agent(debby/polly)明确不可用,配了就可用。

- **Why this priority**:owner 明确要求"和其他一样,不是默认";去掉全局回退后,所有 provider 语义一致,避免"显示未配置却能跑"的迷惑。
- **可独立测试**:全新企业未配 Anthropic → claude agent 报不可用;配上 `ANTHROPIC_API_KEY` → claude agent 可用。
- **验收场景**:
  1. **Given** 企业未配 Anthropic **When** 看配置页 **Then** Anthropic 显示"未配置"(无"平台默认"徽标)。
  2. **Given** 企业未配 Anthropic **When** 用 debby(claude-sdk)对话 **Then** 明确报 anthropic 未配置/agent 不可用。
  3. **Given** 管理员用 API key 配了 Anthropic **When** 再用 debby 对话 **Then** 可用;配置页只出现"API key"一种类型(无"订阅 token"选项)。

### User Story 3 — 配置页 provider 列表符合 owner 预期 (Priority: P2)
配置页依次展示 Anthropic (Claude)、OpenAI (Codex)、MiniMax、DeepSeek;不再有 Gemini。

- **可独立测试**:打开配置页 → 看到四个 provider、无 Gemini。
- **验收场景**:
  1. **Given** 打开配置页 **When** 查看 provider 列表 **Then** 依次是 Anthropic、OpenAI(Codex)、MiniMax、DeepSeek,无 Gemini。

### Edge Cases
- 只配了 MiniMax 没配 DeepSeek 时用 deepseek agent → 明确不可用,**绝不**回落到 MiniMax 的凭据(隔离/正确性)。
- 管理员填了 `${VAR}`/`$VAR` 形式的伪值 → 前后端都拒(沿用现有字面值门)。
- 去掉平台全局 claude 回退后,**已存在企业**在补配 Anthropic 前 claude 类 agent 会不可用 → 需在 runbook / 迁移说明里显式告知(不静默砍能力)。
- 跨 provider 凭据串号:MiniMax 的 key 绝不能被注入成 DeepSeek 的 env(反之亦然)——env 槽必须彼此独立且命名不重叠。

## Requirements

### 功能需求(可测)
- **FR-001**:配置页 MUST 展示 Anthropic (Claude)、OpenAI (Codex)、MiniMax、DeepSeek 四个 provider,MUST NOT 展示 Gemini。
- **FR-002**:Anthropic MUST 只提供 **API key** 一种凭据类型;MUST NOT 出现"订阅 token"选项;MUST NOT 显示"平台默认"态。
- **FR-003**:MiniMax 与 DeepSeek MUST 各有独立的沙箱注入凭据槽(env 名彼此不重叠、且不与 `OPENAI_*` 重叠),使两者能**同时**配置且各自生效。
- **FR-004**:系统 MUST 为 MiniMax、DeepSeek 各提供一个可运行的 harness,分别读各自的凭据槽;某 provider 未配置时其 agent MUST 明确不可用,MUST NOT 回落到别的 provider 的凭据。
- **FR-005**:新企业置备 MUST 得到 5 个默认智能体(minimax、deepseek、debby、codex、polly);minimax MUST 用 minimax harness、deepseek MUST 用 deepseek harness。
- **FR-006**:平台 MUST NOT 再全局注入 Anthropic 订阅 token 作为默认回退;claude 类 agent 的凭据 MUST 来自企业配置的 `ANTHROPIC_API_KEY`。
- **FR-007**:所有凭据写/读 MUST 沿用现有红线——授权经 `can()`(enterprise-admin)、值绝不 log/审计/回显、只收字面值、每企业硬隔离(只碰自己 alias 文件)。

### 关键实体(概念级)
- **Provider**:一个可配置凭据的模型来源(Anthropic/OpenAI/MiniMax/DeepSeek);有展示名、凭据类型、独立的注入槽。
- **凭据槽(Injection Slot)**:某 provider 注入受管沙箱的一组 env 名(key + 可选 base_url);各 provider 互不重叠。
- **Harness**:agent 运行时,决定读哪个凭据槽、调哪个 endpoint;MiniMax、DeepSeek 各有专属 harness。
- **默认智能体**:新企业置备即得的本企业 agent;本次由 4 增至 5(加 deepseek)。

## Success Criteria
- **SC-001**:同一企业同时配 MiniMax 与 DeepSeek,两者都"已配置",且各自 agent 都能对话成功(可核验读的是不同凭据)。
- **SC-002**:Anthropic 在配置页无"平台默认"徽标、只有 API key 类型;未配置企业的 claude 类 agent 明确不可用,配置后可用。
- **SC-003**:配置页 provider 列表 = {Anthropic, OpenAI(Codex), MiniMax, DeepSeek},无 Gemini。
- **SC-004**:某 provider 未配置时其 agent 不可用且**绝不串用**别的 provider 凭据(隔离/正确性可被验证)。
- **SC-005**:dev 与 prod 用同一 fork 源/构建产物(新增 harness 随 fork 自编译,parity 可核验)。

## Assumptions(假设与依赖)
- MiniMax、DeepSeek 均为 OpenAI 兼容 chat/completions 端点;可复用 openai-agents 执行器语义,仅凭据槽/endpoint 不同(**待 design 探针实测确认**,不静默猜)。
- fork 的 harness 由 `_HARNESS_MODULES` 名→模块注册;新增 harness 名即可被 agent 选用(**待探针实测**)。
- 受管沙箱注入的 env 名单由 `deploy/dev/omnigent/config.yaml` 的 `sandbox.docker.env` 列出,值按企业文件 `secrets/model-config/<alias>.json` 解析。
- 去平台 claude 回退不影响 codex 默认 agent(codex 走独立凭据/订阅)。

## 未决
- (无 `[NEEDS CLARIFICATION]`;harness 复制方式、凭据槽命名、endpoint 默认值以 design 探针 + 决策规则处理。)

---
> **Spec 质量自检**:
> - [x] 无实现细节(env 名/模块路径/镜像都进 design)
> - [x] 面向用户价值、可读
> - [x] 用户故事带优先级 + 各自可独立测试
> - [x] FR 可测;`[NEEDS CLARIFICATION]` = 0
> - [x] Success Criteria 可度量
> - [x] 范围有界;Assumptions/依赖已列
