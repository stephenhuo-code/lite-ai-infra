# ADR-026: Dev Workspace = 自建 client + omnigent 作 agent 后端(②-⑥);授权三分层(认证/数据/agent 行为)

- 状态:**Proposed(2026-06-26)**。owner 已在 brainstorm 中拍定方向(C:自建 React19 client 经 API 驱动 omnigent;omnigent 作 ②-⑥);**正式 Accept 留待 spec/DoR 过门 + Task0 docker 探针实跑确认**(boot + OIDC→KC + 我们的 MCP 工具被 agent 调用 + 沙箱限工作目录)。
- 决策人:owner
- 相关:**升级 [ADR-019](./ADR-019-exit5-gui-bff-resequence.md) 的 Plan 9 定义**(从"code-server + Remote-SSH 半天版"→ agent 工作台);**沿用衔接** [ADR-023](./ADR-023-catalog-driven-datasets.md)(catalog 注册)、[ADR-024](./ADR-024-owner-based-dataset-ownership.md)(owner 授权 can())、[ADR-025](./ADR-025-keycloak-organizations-as-enterprise.md)(KC Organizations 身份);**正交并衔接** [ADR-011](./ADR-011-authorization-pdp-cerbos.md)(Cerbos 授权路线);**遵循 constitution** §2.4(can() 单一授权出入口)、§1.6(企业硬隔离)、§3.0.2(契约优先)、§5.2(secret 不入库)、§5.3(dev-prod parity)。
- 调研:[spike RESULTS 2026-06-26 omnigent 可用性](../superpowers/spikes/2026-06-26-omnigent-feasibility.md)(源码级:openapi 53 端点 / embed.tsx 版本鸿沟 / OIDC→KC / policy / sandbox 实证)。design:[`2026-06-26-dev-workspace/design.md`](../superpowers/plans/2026-06-26-dev-workspace/design.md);spec:owner 待写。

---

## Context

S1 出口④ 的降级项 **Plan 9 Dev Workspace** 原定"code-server + Remote-SSH 半天版"。owner 重定义为 **agent 驱动的数据开发台**:基于数据目录(catalog)的数据集做**数据探查 + 数据管线开发**(兼容 Data-Juicer + Python)。UI = 左树(工作目录 / catalog / git 树)+ 右侧(agent 对话 + 文件 + 终端)。

自建完整 agent runtime(会话编排 / 沙箱 / harness / 行为策略)成本高、且非平台差异化价值。开源 **omnigent**(`omnigent-ai/omnigent`,Apache-2.0,v0.2.0 alpha)是 meta-harness,正好提供 ②-⑥(Server/Host/Runner/Harness/沙箱/policy)。spike 源码实证三承重墙均利好:① 有 openapi 契约(但 embed.tsx 期望 React18/RR6,与我们 React19/RR7 鸿沟)② OIDC 原生可指我们 KC ③ 沙箱/policy 齐全,数据隔离可落在"我们的 MCP 工具(can())"。

同时引出授权边界问题:omnigent 未来提供"4级权限" + PolicyEngine(ALLOW/DENY/ASK)。需明确**哪种授权归谁**,避免把平台的租户/数据硬隔离(宪法红线)外包给一个不懂我们企业/owner 模型的外部引擎。

## Decision

### 1. 采用 omnigent 作 Dev Workspace 的 agent 后端(②-⑥),自托管

- omnigent(Apache-2.0,self-host docker)提供 Server(FastAPI)/Host/Runner(每会话进程 + bwrap 沙箱)/Harness(claude-sdk)/policy。**非自建 agent runtime/沙箱**。
- **部署形态 = 预构建镜像,不 fork 改源码**(spike 实证):用 `ghcr.io/omnigent-ai/omnigent-server`(+ runner `omnigent-host`);认证(header-auth)、UI(我们自建,不用其 ap-web)、数据工具(每会话 API 注册我们的 MCP)全经**配置/API**,均无须改码。**钉 `:vX.Y.Z` 或 `:sha-<short>`(不用 `:latest`),prod 可镜像到自有 registry**(供应链 + 版本钉定)。
- alpha 依赖:**版本钉定 + Task0 探针先验**;两套后端(我们的服务 + omnigent)并存运维。

### 2. Client 自建(React19),经 omnigent API 驱动 —— 不嵌入、不 iframe

- 在我们 React19 控制台新增「Dev Workspace」页,**对着 omnigent `openapi.json`(REST)+ WS 自建瘦客户端 UI**(左树 + chat + 文件 + 终端)。
- **否决直接 React-island 嵌入**(`embed.tsx` 设 React/react-router 为 externals,期望 host React18/RR6;我们 React19/RR7,RR6↔7 差异大 → 高风险)。**否决 iframe**(UI 割裂,catalog 进不了统一左树,UX 不达"左树右对话"目标)。代价:自建 chat/files/terminal 工作量,owner 已认可(开发时间可延长)。
- 前端经**我们的 BFF 反代** omnigent(REST + WS),注入身份(header-auth)+ CSRF;**前端不持 token**(沿用现模型)。

### 3. 授权三分层 + 红线(本 ADR 核心)

> 可控链路全图见 [design assets/control-chain.svg](../superpowers/plans/2026-06-26-dev-workspace/assets/control-chain.svg)。

| 关注 | 谁管 | 依据 |
|---|---|---|
| **认证(你是谁)** | **Keycloak**;omnigent 前门用 **header-auth**(BFF 注入身份头,非 omnigent OIDC,见下)| ADR-025 / spike RESULTS ② |
| **租户/数据授权(能否碰这份企业数据)** | **我们 `can()`(→Cerbos),落在我们的 MCP 工具内**(每会话令牌绑定 KC 身份)| §2.4 单一出入口 / §1.6 硬隔离 |
| **agent 行为治理(shell/tool/cost/working_dir/危险操作 ASK)** | **omnigent PolicyEngine**(自带,我们没有)| spike RESULTS ③ |
| **会话协作(谁能 view/edit/run 某会话)** | **omnigent session permissions**(限我们租户内)| spike RESULTS ③ |

- **数据集受控机制(承重)**:omnigent 每会话 MCP 注册体**无 header/env 转发槽**(spike 实证)→ 它不转发用户身份给我们的 MCP 工具。故数据控制**由我们自己绑定**:BFF 会话创建时铸**每会话令牌** `token→(sub=owner, 企业 alias, 会话)`,用 **http transport** 注册我们的 MCP server(URL 内嵌令牌);agent 调工具时 MCP server **校验令牌→还原同形 `Context`→每次 `can()`**(企业硬隔离 + owner,ADR-024)。**不变式**:agent 即使放飞,只能以该会话绑定的那一个用户、只经我们暴露的工具、每次被 `can()` 拦;**不依赖信任 omnigent 转发身份**(对 alpha 第三方 = 防御纵深)。
- **前门用 header-auth 非 OIDC**(理由,非"OIDC 差"):纯 env 配置零改码(spike 实证);契合"自建 client + BFF 单信任边界"(前端不持 token、omnigent 不直达);**且 OIDC 的原生 KC 身份到不了 MCP 工具(无转发槽),对数据集受控零增益**。header 模式强制:BFF MUST 剥离客户端伪造的同名身份头;omnigent server MUST 不可直达。
- **可扩展(group + role / Cerbos)**:未来加 organization group + per-group role,**链路/令牌/omnigent/MCP 注册全不变**,只动既有缝——令牌映射多带 `groups[]/roles[]`、`parse_context` 多读 claim、`can()` 内换 Cerbos(调用点不变)。owner(sub)与 group 共存,agent 路径自动继承(走同一道 `can()` 闸)。
- **红线:租户/数据隔离绝不外包给 omnigent policy。** omnigent 的 policy 作用对象是 agent 动作,不懂我们的企业/owner/catalog 模型;把硬隔离交给它 = 违 §2.4/§1.6 且它做不到。

### 4. Cerbos(S2)与 omnigent policy 正交、不一起实现 —— MCP 工具是接缝

- 两者解不同问题:**Cerbos = 数据/资源授权 PDP(`can()` 的演进,管 group 共享/细粒度)**;**omnigent PolicyEngine = 会话内 agent 行为治理**。
- **Plan 9 不依赖、不拉入 Cerbos**:数据授权 v1 用现有 `can()`(在我们 MCP 工具里),agent 行为用 omnigent 自带 policy,两者现在即可跑。
- S2 Cerbos 落地时,**MCP 工具是接缝**:把工具内 `can()` 换 Cerbos 即可,**无需碰 omnigent**、无需两者一起实现。可选 v-next:omnigent 自定义 policy 在 agent 调数据工具时回调 Cerbos(默认走"工具内调授权"更简单)。

## Consequences

**正面**:省造 agent runtime/沙箱/harness/policy(难且非差异化);统一 UX(左树右对话,catalog 在同一树);隔离红线守住(can() 仍是数据授权唯一出入口);Cerbos 与 omnigent 解耦,各自独立演进;新增 agent 行为治理能力(我们原先没有)。

**负面 / 风险**:① omnigent alpha 依赖,API 可能变 → 预构建镜像钉 release tag + 升级策略 ② 两套后端并存运维 ③ 自建 agent UI(chat/files/terminal)工作量 ④ BFF 需代理 WS ⑤ **header-auth 信任义务**:BFF 必须剥离客户端伪造身份头 + omnigent 不可直达(否则身份可冒充)⑥ **每会话令牌**需 TTL/撤销/仅内网可达,且优先"header 带令牌"避免 URL 令牌入日志(Task0 定)⑦ 模型 key(§5.2 secret)+ 成本治理(用 omnigent policy 成本上限)。

## 否决的备选

- **直接 React-island 嵌入 omnigent ap-web**:React19/RR7 vs 18/RR6 鸿沟,高风险。
- **iframe omnigent ap-web**:最省最稳,但 UI 割裂、catalog 进不了统一左树,不达交互目标。
- **全自建 agent runtime(不用 omnigent)**:重造沙箱/harness/会话编排,成本高、非差异化价值。
- **把租户/数据隔离交给 omnigent policy 引擎**:违宪(§2.4/§1.6)+ omnigent 不懂我们的模型,做不到。
- **前门用 OIDC**:本架构下零增益(原生身份到不了 MCP 工具)且与 BFF 单边界冲突;仅当改"前端直连 omnigent(不走 BFF)"才考虑。
- **fork omnigent 改源码**:认证/UI/数据工具均可经配置/API 达成,无须改码;改码徒增维护与升级负担。

## 待 Task0 探针确认(进 writing-plans 前/首任务)

docker 起 omnigent(预构建镜像)→ ① **header-auth** 模式 BFF 注入身份头被接受(login 通)② **http transport MCP server(URL 嵌令牌)被 agent 调用 + 令牌还原 ctx 成功**;核验有无 header/env 转发旁路(有则优先 header 带令牌)③ 沙箱 + working_dir 限到工作目录;对象存储工作目录 ↔ 沙箱本地盘挂载/同步 ④ BFF 反代 REST+WS。带退化规则:某项不成则记录 + 调整集成形态(回 design)。
