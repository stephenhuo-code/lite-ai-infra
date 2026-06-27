# ADR-027: Dev Workspace 全容器化 + per-user managed host(订阅凭据 / 真流式 / parity)

- 状态:**Proposed(2026-06-27)**。owner 已拍定关键方向(全容器化、per-user managed host、用 claude/codex 个人订阅、必须流式、sandbox 先不上);**正式 Accept 留待 DoR 过门 + 两个探针实跑确认**(managed-host 在我们 infra 上 server-launch、流式 delta 真达 SSE)。
- 决策人:owner
- 相关:**承接并修订** [ADR-026](./ADR-026-dev-workspace-omnigent.md)(omnigent 作 agent 后端 + 自构建单一源三层 + 授权三分层 + 承重墙);**遵循 constitution** §5.3(dev-prod parity)、§1.6(企业硬隔离)、§2.4(can() 单一授权出入口)、§5.2(secret 不入库)。
- 调研:[research 2026-06-27 omnigent 容器化/runner/harness/流式](../superpowers/plans/2026-06-26-dev-workspace/design-containerization.md#依赖与引用)(源码级,四面:host 镜像+认证、runner 派生+沙箱、harness/model、流式)。design:[`design-containerization.md`](../superpowers/plans/2026-06-26-dev-workspace/design-containerization.md)。

---

## Context

ADR-026 采纳 omnigent 作 agent 后端 + **自构建单一源三层**(dev 本地 build / CI 推 registry / prod pull same-bits)。但 **dev 落地时为图省事走了捷径**:只有 omnigent **server** 进 docker,**host/runner 跑 native 源码**(`uv run --project third_party/omnigent omnigent host`),且 omnigent server 开 **单用户模式**(`AUTH_ENABLED=0`)、模型用 **owner 个人 claude 订阅**(`CLAUDE_CODE_OAUTH_TOKEN`)。

这破坏了多条地基约束,是**技术债**而非合理设计:

1. **破 §5.3 parity**:dev host=native 跑源码、prod host=镜像 —— 架构与版本不一致,dev 验证不能代表 prod;omnigent 架构一致性无保证。
2. **不能多用户**:native 单用户 host 一切归 `local`,无法服务多企业多用户。
3. **无版本保证**:native 跑工作树源码,prod 跑镜像,两者字节/依赖不同。
4. **流式缺失**:dev 的 host **native auto-create terminal** 路径下,claude-native/codex-native 的流式 delta 都没送达 SSE(实测:回复整段落 `/items`,SSE 无 `output_text.delta`)。

owner 要求重做设计,四项需求:① host 跑容器、多用户共用 ② runner 按 session 动态派生 + 授权 + 沙箱 ③ host/harness 可配(omnigent 本就支持)④ 必须流输出(omnigent 本就支持)。调研(四个源码级 research agent)确认四项**全部可行**,关键事实见 design。

## Decision

### 1. 全容器化:server + host 都用 omnigent 镜像(取代 native 源码 host)

- omnigent `Dockerfile` 已有 `--target host`(含 claude/codex CLI、tmux、bwrap),`scripts/omnigent_build.sh` **本就同时构建 server + host 两镜像**。dev 与 prod **同镜像**(经 ADR-026 三层:dev 本地 build same-source / CI 推 registry / prod pull same-bits)。
- **native 源码 host 退役**:`make ws-host-up` 那条 `uv run omnigent host` 仅作"改 omnigent 源码后本地快验"的临时手段,**不再是 dev 常态拓扑**。dev 常态 = 容器化 host(同 prod)。
- 恢复 §5.3 parity:dev 与 prod 跑同一套 omnigent 镜像 + 同架构。

### 2. omnigent server 开 header-auth 多用户(取代单用户)

- `OMNIGENT_AUTH_ENABLED=1` + header-auth(沿用 ADR-026 §3:BFF 注入身份头、剥伪造头、omnigent 不可直达)。多用户由此成立。

### 3. per-user managed host(每用户一个沙箱 host,可多 session)

- 用 omnigent **server-launched managed host**(`host_type="managed"`):host 身份持久(`hosts` 行带 launch-token digest + sandbox 代),sandbox 可重建,**按 owner 绑定**。
- **每用户一个 host、一 host 多 session**(owner 决策)。强隔离边界 = **per-user host 容器**(跨用户隔离在容器边界,硬)。
- 容器化 host 认证用 **managed host token**(`OMNIGENT_HOST_TOKEN` → `X-Omnigent-Host-Token` 头),由 server 签发(解决 ADR-026 dev 阶段 header 模式 host 401 的根因)。

### 4. runner 每会话动态派生 + 授权;sandbox=none(显式推迟硬化)

- 沿用 omnigent 现成机制:`launch_runner` 每会话 `subprocess.Popen` + binding-token 绑 runner_id + 对 `conversation.runner_id` 原子 CAS + **双 owner 检查**(host owner + session owner)。
- **sandbox `type: none`,作为后硬化项显式推迟到 vNext**(owner 决策)。理由:强隔离边界是 per-user host 容器(跨用户硬);未上沙箱的弱点(同一用户多 session 间共享文件系统、agent 能读到该用户 host 内注入的订阅凭据)都落在**该用户自己的边界内**,风险可接受。prod 硬化时上 `linux_bwrap`(workspace mount 隔离 + dotfile 屏蔽 + egress 规则),单独立项。

### 5. harness/model 用 per-user 个人订阅(native harness)

- harness 在 agent spec `executor.config.harness`,**per-agent、改 spec 即切、同 host 可并存多 harness、不重启 host**。
- **用 claude-native(claude 订阅)/ codex-native(codex 订阅)**(owner 决策:先用订阅,不引入产品级 API key/网关)。**否决**(留 vNext):SDK harness(claude-sdk/openai-agents)+ 产品 API key/网关 —— 它流式最稳(逐 token、零 hook),但需产品级凭据,owner 选先用订阅。

### 6. per-user 订阅凭据流(本 ADR 新增承重设计点)

- 「每用户一个 host + 用订阅」的必然产物:User A 的 host 容器要有 A 的 claude/codex 订阅凭据。
- **捕获**:onboarding 让用户做 `claude setup-token` / `codex login`,把产出的 OAuth token / `auth.json` 提交给产品。
- **存储**:**per-user 加密存储**(§5.2,绝不明文入库/入仓);凭据库按 `user_id` 持有 `{claude_oauth_token, codex_auth_json}` 密文。
- **注入**:server 启动该用户 managed host 时,把凭据注入容器(env `CLAUDE_CODE_OAUTH_TOKEN` / 写入 `CODEX_HOME/auth.json`)。omnigent managed-host launch 支持 env 注入 + 预留 "managed credentials" 接缝(`codex_native.py` 已注释)。
- **吊销/轮换**:用户可重置 → managed host 重建拾取新凭据。

### 7. 流式:经 managed/server-launched 路径恢复

- dev native auto-create 路径有 codex forwarder 的 subscribe race(thread 未就绪 → fallback rollout → 无 delta)。**server-launched/managed 路径**由 runner 控制 TUI 生命周期、就绪后再订阅 → **codex-native 逐 token 流式**;**claude-native 段落级 chunk**(MessageDisplay hook 天然粒度,非逐字)。
- 前端走增量流(`output_text.delta` / `external_output_text_delta`)渲染 + `/items` 兜底对账(替换现 dev 的纯 items 轮询)。
- **粒度事实(owner 已接受)**:codex 逐 token、claude 段落级,二者都是增量流式,粗细不同。

### 8. 承重墙不变

- BFF 铸每会话令牌 → 我们的 MCP server 校验令牌→`Context`→每次 `can()`(企业硬隔离 + owner)→ 数据。**与 omnigent 自身身份正交**(ADR-026 §3)。多用户化 / 容器化 host **不改**这条;数据隔离始终在我们 MCP 层强制。

## Consequences

**正面**:恢复 §5.3 parity(dev=prod 同镜像);多用户成立;真流式(managed 路径);强隔离边界 = per-user 容器;harness 可配(改 spec 即切);承重墙不变。

**负面 / 风险**:① **per-user 凭据流是新工作量**(捕获/加密/注入/吊销),且是新攻击面(密文管理 §5.2)② managed-host 在**我们自有 infra**(aliyun ECS,ADR-022)上 server-launch 的 provider 需落实(omnigent 现成 provider 多为云沙箱 Modal/Daytona/CoreWeave/OpenShell)→ **探针待确认**③ **sandbox=none** 是已知推迟项(prod 必补)④ 订阅绑个人 = 非完全产品化(规模化时换网关,留 vNext)⑤ 两套后端(我们服务 + omnigent)+ per-user host 编排运维成本⑥ 流式 delta 真达 SSE 在我们部署里**未实证** → 探针待确认。

## 否决的备选

- **继续 native 源码 host**:破 §5.3 parity、不能多用户、无版本保证 —— 本 ADR 要消除的技术债。
- **产品级 API key / 网关 + SDK harness**:流式最稳(逐 token),但 owner 决策先用个人订阅;留 vNext(规模化/去个人绑定时启用)。
- **单共享 host 多用户(owner 隔离)**:比 per-user host 隔离弱、且 session↔host 1:1 绑定有调度局限;owner 选 per-user。
- **现在上 bwrap 沙箱**:owner 决策先不上,显式推迟到 prod 硬化。

## 待探针确认(进 writing-plans 前)

- **P1 managed-host provider**:omnigent server 能否在**我们 infra**(docker / k8s on ECS)上 server-launch per-user managed host?现成 provider 够用还是需自写一个 docker/k8s provider?决策规则:有可用 provider → 配置之;无 → 评估自写成本,或退到"预起 per-user host 容器 + 静态注册"形态(回 design)。
- **P2 流式 delta 真达 SSE**:容器化 server-launched 路径下,codex-native 逐 token delta、claude-native 段落 delta 是否真到 `/v1/sessions/{id}/stream`?决策规则:到 → 前端走增量流;codex 到/claude 不到 → 默认 codex-native;都不到 → 修 forwarder 或退回 items 轮询(回 design)。
