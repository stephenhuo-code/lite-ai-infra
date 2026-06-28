# Spec(需求):Plan 9a — omnigent 集成(对话窗 MVP)

> 需求层(WHAT/WHY)。**禁**技术栈/契约 schema/实现(归 design.md / tasks)。
> **状态**:Draft · **关联**:S1 出口④ 降级项 Plan 9 拆分的第一半(9a);承接 ADR-025(KC 企业化);新 ADR-026(omnigent 集成) · **输入**:owner —— "plan9 拆两个:9a 只做 omnigent 集成 + workspace 对话窗,每用户能和 omni agent 对话;server/host 容器化;客户端复用现有 UI;omnigent 用我们 fork 自编译。9b 再做 dev workspace。"

## Goal & 价值
- **目标**:把 omnigent 作为一个**自托管、容器化、多用户**的 agent 后端集成进来,让平台用户在控制台「Workspace」里**和 AI agent 对话**(就这一件事跑通)。
- **价值**:① 给平台加上"和 agent 对话"的能力地基 ② 把最难、最该先 de-risk 的部分(omnigent 容器化部署 + 多用户认证 + 我们自维护 omnigent 代码)先打通,9b 的数据工作台才有地基可建。
- **成功长这样**:两个不同用户各自登录控制台 → 进 Workspace → 各自和 agent 对话、互不可见;agent 跑在各自隔离的沙箱里;整套 server/host 是我们自己编译的镜像,dev 和 prod 同源。

## 范围
- **In(9a 做)**:
  - Workspace 菜单下**仅一个「对话窗」**:发消息、看 agent 流式回复、新建/切换会话。
  - 多用户:经我们 **Keycloak** 登录,每用户独立身份、会话、沙箱;用户间隔离。
  - omnigent **server + host 容器化自托管**;host 走 **managed**(server 按用户/会话拉起隔离沙箱)。
  - omnigent 代码**我们自己维护 + 自己编译镜像**(fork 自构建)。
  - 前端**复用现有控制台 UI** 的对话窗,经 BFF 反代 omnigent。
- **Out(9a 不做)**:任何**数据访问**——左树 catalog、文件/终端窗、数据探查/采样、管线、把 agent 接到我们的数据(MCP 工具 / can() 承重墙)。9a 的 agent 是"通用对话 agent",**碰不到我们的企业数据**。
- **推迟(Plan 9b)**:dev workspace 全貌(左树 catalog/git、文件 monaco/终端 xterm、MCP 数据工具 + 企业/owner `can()` 承重墙、Data-Juicer 管线、工作目录 OSS 持久化)。

## User Scenarios & Testing

### User Story 1 — 用户和 agent 对话 (Priority: P1)
登录平台的用户进入 Workspace,发一条消息,agent 回复;回复是**逐步出现**的(不是干等很久再整段蹦出)。这是 9a 的 MVP 核心切片。

- **Why this priority**:这是 9a 的存在理由——"能和 agent 对话"。它通了,omnigent 集成的地基(部署+认证+会话+流式)就立住了。
- **可独立测试**:一个用户登录 → 进 Workspace → 发"你好" → 看到 agent 回复逐步出现,即证伪通过。
- **验收场景**:
  1. **Given** 用户已登录控制台 **When** 进入 Workspace 对话窗发一条消息 **Then** 看到 agent 的回复,且回复内容是渐进出现的(流式)。
  2. **Given** 已有一轮对话 **When** 继续发第二条 **Then** agent 在同一会话上下文里接着回。
  3. **Given** 用户新建一个会话 **When** 发消息 **Then** 新会话独立、不带上一会话的上下文。

### User Story 2 — 多用户隔离 (Priority: P1)
两个不同用户各自登录,各自和 agent 对话,**彼此看不到对方的会话,agent 跑在各自隔离的沙箱里**。

- **Why this priority**:多租户平台的底线;和 P1 同级——没有隔离的多用户对话不可上线。
- **可独立测试**:用户 A、B 分别登录 → 各发消息 → A 的会话列表里没有 B 的会话;后台看 A、B 的 agent 在不同沙箱。
- **验收场景**:
  1. **Given** 用户 A 和 B 各有自己的会话 **When** A 查看自己的会话列表 **Then** 只看到 A 自己的,看不到 B 的。
  2. **Given** A 拿到(猜到)B 的会话/沙箱标识 **When** A 试图访问 **Then** 被拒(无权)。
  3. **Given** A 和 B 同时在对话 **When** 各自 agent 执行 **Then** 跑在各自独立的沙箱,互不干扰。

### User Story 3 — omnigent 我们自维护、自编译 (Priority: P2)
作为平台维护者,我能改 omnigent 的代码,并用**我们自己编译的镜像**部署;dev 和 prod 跑的是同一份源、同样的构建产物。

- **Why this priority**:owner 明确"未来要改 omnigent 代码"。不锁死这条,后续改码无从落地;但它不阻塞 P1/P2 的对话演示,故 P2。
- **可独立测试**:在我们 fork 里改一行 omnigent 代码 → 重新编译镜像 → 起栈 → 看到改动生效。
- **验收场景**:
  1. **Given** omnigent 源在我们自己的仓 **When** 改一处并编译 server/host 镜像 **Then** 部署后改动可观察。
  2. **Given** dev 与 prod **When** 比对所用镜像 **Then** 来自同一源(dev 本地构建 / prod 用 CI 发布的同字节)。

### Edge Cases
- 当用户**没有可用沙箱 host**(还没起/起失败)时发消息会怎样?→ 应有明确反馈,不静默卡死。
- 当 agent 回复中途**沙箱/连接中断**时会怎样?→ 会话不崩,给出可感知的失败态。
- 当用户**未登录/会话过期**访问对话窗会怎样?→ 跳登录,绝不放行。
- 当用户伪造他人身份头/会话标识时?→ 被认证/鉴权挡住(隔离不变式)。
- 当模型凭据缺失/失效时 agent 起不来怎样?→ 明确报"agent 不可用",不伪装成功。

## Requirements

### 功能需求(可测)
- **FR-001**:用户 MUST 经平台统一登录(Keycloak)后才能进入 Workspace 对话窗;未认证 MUST 跳登录。
- **FR-002**:用户 MUST 能在对话窗发消息并收到 agent 回复,回复 MUST 以**流式/渐进**方式呈现。
- **FR-003**:用户 MUST 能新建会话、在自己的多个会话间切换;每会话上下文独立。
- **FR-004**:系统 MUST 按用户隔离会话与沙箱——用户 MUST NOT 看到或访问他人的会话/沙箱(隔离不变式)。
- **FR-005**:每个用户的 agent MUST 运行在**服务端按用户/会话拉起的隔离沙箱**里(managed host),沙箱归属在服务端锁定。
- **FR-006**:agent 在 9a MUST NOT 能访问平台的企业数据(无数据工具接入);9a 的对话是通用对话。
- **FR-007**:omnigent server/host MUST 以**我们自己编译的容器镜像**部署,源码 MUST 在我们可修改的仓库里;dev 与 prod MUST 同源(parity)。
- **FR-008**:前端 MUST 复用现有控制台 UI 的对话窗,且 MUST NOT 在前端持有 omnigent 的访问令牌(经 BFF 反代)。

### 关键实体(概念级)
- **对话会话(Conversation)**:某用户和 agent 的一段对话;归属一个用户;含消息历史;彼此隔离。
- **用户(User)**:经 KC 认证的平台用户;拥有自己的会话与沙箱。
- **沙箱 host(Managed Host)**:服务端为用户/会话拉起的隔离执行环境,agent 在其中跑;归属锁定到用户。
- **消息(Message)**:会话里的一条 user/assistant 内容;assistant 内容渐进产生(流式)。

## Success Criteria
- **SC-001**:用户登录后 ≤ 3 步(进 Workspace → 输入 → 发送)即可和 agent 开始对话。
- **SC-002**:agent 回复**可见地渐进出现**(首段可见时间显著早于整段完成),非"长时间空白后整段蹦出"。
- **SC-003**:两个并发用户各自对话互不可见、互不干扰(隔离可被验证:A 列表无 B 会话;越权访问被拒)。
- **SC-004**:平台维护者改一处 omnigent 代码 → 重编译 → 部署后改动生效,**全程不依赖上游预构建镜像**。
- **SC-005**:dev 与 prod 所用 omnigent 镜像来自同一源(同 fork commit / 同构建产物),parity 可核验。

## Assumptions(假设与依赖)
- 依赖既有 **Keycloak**(realm lite-ai)做认证;omnigent 作为标准 OIDC 客户端接入(调研已验证原生支持)。
- 依赖既有控制台前端 + BFF(gateway)作为唯一信任边界(前端不持 token,沿用现模型)。
- 模型凭据(让 agent 能调用 LLM)在 9a **由平台侧统一提供给 managed 沙箱**(产品级,非每用户个人订阅);个人订阅模型若需要留待后续评估(记 Assumptions,不在 9a 纠结)。
- managed 沙箱在**我们自托管基础设施(docker)**上拉起(非云 SaaS provider);具体落地方式待探针实测(见 design / DoR #4)。
- 9a 的 agent 无数据访问,故**无企业数据隔离风险**(承重墙是 9b 的事)。

## 未决
- (无 `[NEEDS CLARIFICATION]`;凭据模型与 managed 沙箱落地方式以 Assumption + design 探针处理,不静默猜。)

---
> **Spec 质量自检**:
> - [x] 无实现细节(端点/镜像名/env 都进了 design,不在此)
> - [x] 面向用户价值、可读
> - [x] 用户故事带优先级 + 各自可独立测试
> - [x] FR 可测;`[NEEDS CLARIFICATION]` = 0
> - [x] Success Criteria 可度量、技术无关
> - [x] 范围有界(只对话窗;数据全推迟 9b);Assumptions/依赖已列
