# Design(设计):Plan 9a — omnigent 集成(对话窗 MVP)

> 设计层(HOW)。对应 [spec.md](./spec.md)。决策落 [ADR-026](../../../adr/ADR-026-omnigent-integration.md)。**核心原则:把 omnigent 当一个按官方方式部署的独立服务用,不手搓、不硬改其内部**(上一轮失败正因手搓底层 API + 私改内部)。

## 架构

### 拓扑(全官方方式 + 全容器化)
```
浏览器 ──→ 控制台前端(现有 React,新增 Workspace 对话窗)
            │ (同源,前端不持 token)
            ▼
        BFF / gateway(现有,唯一信任边界)── 反代 omnigent REST + WS(SSE/stream)
            │                                   注入已认证身份 / 剥伪造头
            ▼
   ┌───────────────────────────────────────────────────────────┐
   │ omnigent server(容器, deploy/docker compose, --target runtime)│
   │   · OIDC ← 我们的 Keycloak(realm lite-ai)                    │
   │   · external-runner 模式:只协调,自己不跑 harness             │
   │   · permission store(资源访问)+ policy engine(行为)         │
   │   · postgres(持久:会话/权限/host 注册)                       │
   │        │ server 按用户/会话 provision                          │
   │        ▼                                                      │
   │   managed host 沙箱(容器, --target host, owner 服务端锁定)    │
   │        └ runner + harness(SDK,进程内)→ LLM(产品凭据)        │
   └───────────────────────────────────────────────────────────┘
   omnigent 源 = 我们的 fork(submodule)→ scripts/omnigent_build.sh 自编译 server+host 镜像
```

- **模块边界**:omnigent = 黑盒服务(server + 它自己拉起的 managed 沙箱);我们只加 ① 前端对话窗 ② BFF 反代。**不进 omnigent 内部接线**。
- **依赖方向**:前端 → BFF → omnigent;omnigent server → 它的 managed 沙箱(内部)。BFF 是唯一对外信任边界,omnigent 不可被客户端直达。
- **宪法一致**:§5.3 parity(fork 自编译,dev/prod 同源);§1.6 隔离(omnigent 多用户 owner 隔离 + 沙箱隔离);§5.2 secret 不入库。**注**:9a agent 无数据访问,§2.4 can() 承重墙是 9b 的事。

### harness 选型:claude-native + 共享订阅(P1 实测回正)
> 早稿写 claude-sdk + 产品 key(误判 claude-native 容器内不行)。**P1 探针推翻并回正**(见 [spike P1](./spikes/P1-managed-docker.md)):
- managed 沙箱内 agent 用 **claude-native harness**——官方 managed docker 流程里终端正常(早先手搓那次卡死是手搓问题)。
- **凭据 = 单一共享 claude 订阅 token**(`CLAUDE_CODE_OAUTH_TOKEN`,经 `sandbox.docker.env:[CLAUDE_CODE_OAUTH_TOKEN]` 注入所有沙箱,零 API 额度)。**勿混注 ANTHROPIC_API_KEY**(触发 apiKeyHelper 与订阅冲突)。**per-user 订阅推迟**(owner 决策 (b));多用户隔离仍在(每用户独立沙箱/会话,仅 token 共享)。
- **流式**:claude-native executor `supports_streaming()=False`,但 transcript forwarder 旁路 → `response.output_text.delta`(best-effort,消息块级,时序滞后于 `response.completed`)。**前端读流别在 completed 停**;`response.output_item.done` 为权威完成项对账。
- 备选:claude-sdk + 产品 key(要逐 token 细粒度流式);codex-native + codex 订阅(对称,可后续加)。

## 沙箱策略(两层)
```
omnigent server 容器(协调,不执行 agent)
   │ 按 用户/会话 provision
   ▼
【外层沙箱】managed host 本身 = 一个隔离环境   ← 用户间强隔离边界(承重)
   │   server 拉起隔离 env 跑 `omnigent host`,owner 服务端锁定 + launch token
   ▼
   runner(host 在沙箱内每会话 spawn)
   └【内层沙箱】agent spec os_env.sandbox(none / bwrap / seatbelt)← 限 agent 自身行为
```
- **外层(host 沙箱)= 用户间隔离的承重边界**:每个 managed host 是 server 按用户/会话拉起的独立环境,A/B 物理隔离。**我们的隔离技术 = docker 容器-per-host**(下方 provider)。
- **内层(runner os_env.sandbox)= 限 agent 自身越权**(shell/文件/网络)。**9a 取 `none`**:外层 managed host 容器已是隔离边界,且 9a agent **无数据访问、SDK harness 进程内**,无需内层;**9b 接数据工具后再按需上 bwrap 收紧内层**(显式推迟)。

### 外层 provider:docker(自写 SandboxLauncher,放我们 fork)
- omnigent **无内置"普通 docker"managed provider**:内置 boxlite=微VM 需 KVM(实测容器内无 /dev/kvm)、modal/daytona/e2b=云 SaaS、kubernetes=k8s pod、openshell=k8s gateway。
- **我们用 docker → 走 omnigent 的 launcher-factory 接缝,自写一个最小 `DockerSandboxLauncher`**(`docker run` 一个 host 容器跑 `omnigent host`、注入 launch token + 产品凭据、`docker rm` 回收)。**模型 C 下它就提交进我们的 omnigent fork**(不是 patch-queue)。备份分支 `dev-workspace-containerization` 有可复用雏形。
- **k8s=pod / 云 provider / boxlite 不写入为我们的路**:k8s 仅"未来若迁 k8s"备选;云=SaaS 不自托管;boxlite 需 KVM。**9a 自托管 = docker SandboxLauncher。**
- **探针 P1 = 实测这条 docker 链路**:server 经我们的 DockerSandboxLauncher provision 隔离容器 host + SDK harness 起 agent + 流式 + 产品凭据注入。

## 核心流程

### 流程 A:登录(KC OIDC)
1. 用户访问控制台 → 未登录 → 现有 BFF 走 KC 登录(已实现)。
2. omnigent server 侧 `AUTH_PROVIDER=oidc` 指向同一 KC realm;用户身份在 omnigent 侧由 OIDC 确立(server 验 token → 颁会话 cookie / BFF 注入身份)。**KC=认证**。

### 流程 B:开对话 + managed 沙箱
1. 前端进 Workspace → BFF 调 omnigent 建会话(host_type=managed)。
2. **omnigent server 自己** provision 一个该用户的隔离沙箱 host(owner 服务端锁定 + launch token;凭据由 server 经沙箱 env 注入,用户凭据不进沙箱)。
3. server 协调 runner 在沙箱内起 agent(SDK harness)。**全程 omnigent 官方流程,我们不手动 launch_runner**。

### 流程 C:对话 + 流式
1. 前端发消息 → BFF 反代 → omnigent server → 沙箱内 agent。
2. agent 流式产出 → omnigent SSE/stream → BFF 反代 → 前端渐进渲染。
3. permission store 保证用户只能访问自己的会话;policy engine 治理 agent 行为(9a 用默认/宽松,无数据工具)。

## 数据模型(多为 omnigent 自带,我们不另造)
- **Conversation**(omnigent):归属 user(owner);消息历史;按 permission store 隔离。**不变量**:用户只能访问自己 owner/被授权的会话。
- **Host**(omnigent,`(owner,name)` 主键 + host_id UNIQUE):managed 沙箱归属锁定到用户;**不变量**:跨用户 host_id 劫持被 IntegrityError 挡(多用户 `allow_host_id_reown=False`)。
- **会话身份**:KC OIDC → omnigent 会话(server 侧),BFF 侧沿用现有已认证会话。
- 我们**不新增**数据实体(9a 无 vault、无 MCP 令牌、无 workspace 持久化——那些是 9b)。

## 授权与安全
- **认证(KC)**:omnigent `AUTH_PROVIDER=oidc`,issuer=我们 KC realm。
- **鉴权(omnigent,两层,原生)**:permission store(谁能 view/edit/manage 某会话/host,owner+级别)+ policy engine(已授权用户的 agent 行为 ALLOW/DENY/ASK)。
- **隔离不变式(本 plan 红线 = 负向测试)**:① 用户 A 列不到/访问不到 B 的会话(permission)② A 用不了 B 的 host(owner 校验 403 + 跨用户 host_id 劫持挡)③ 伪造身份头被 BFF 剥离 ④ omnigent 不可被客户端直达(只经 BFF)⑤ 前端不持 omnigent token。
- **secret(§5.2)**:KC client secret、OIDC cookie secret、模型凭据 —— 经 env/外部 secret 注入,不入库/不入仓。
- **9a 无数据访问**:agent 碰不到企业数据,故无数据越权面(承重墙 = 9b)。

## 非功能(NFR)
- **dev/prod parity(§5.3,核心)**:omnigent = 我们 fork(submodule 钉 commit)→ `scripts/omnigent_build.sh` 自编译 server+host;**dev 本地 build / CI build+push registry / prod pull same-bits**;不依赖上游预构建。
- **流式**:SDK harness 原生 token 级 delta → SSE;前端渐进渲染(SC-002)。
- **并发/隔离**:每用户独立会话 + 独立 managed 沙箱;omnigent server 多副本经 DB(postgres)共享 runner registry。
- **部署拓扑**:aliyun ECS(ADR-022);omnigent server + postgres 容器;managed 沙箱由 server 在我们 docker 基础设施上拉起(落地方式见探针 #4)。
- **安全**:OIDC cookie secret / KC client secret / 模型凭据经 env;BFF CSRF 沿用现有。

## omnigent 自维护(模型 C:fork 作 submodule)
- fork omnigent 到我们自己的仓 → 在 fork 里**正常 git commit** 改 → lite-ai-infra 把 fork 当 **submodule** 钉到某 commit。
- `scripts/omnigent_build.sh` 从 submodule(我们的 fork)build `--target runtime`(server)+ `--target host`(沙箱镜像)。
- 升级:把上游 omnigent 新 tag merge 进我们 fork。
- 修订 ADR-026 旧思路:**用 fork-as-submodule 取代 patch-queue**(patch-queue 改一次重生成、体验差;owner 明确会持续改 omnigent → 走 fork)。

## 依赖与引用
- **决策**:[ADR-026](../../../adr/ADR-026-omnigent-integration.md)(本 plan);承接 [ADR-025](../../../adr/ADR-025-keycloak-organizations-as-enterprise.md)(KC)、[ADR-022](../../../adr/ADR-022-ci-on-aliyun-ecs.md)(ECS)。
- **调研事实(omnigent 源码级,2026-06-28,已研判可信)**:
  - 官方容器部署 = `third_party/omnigent/deploy/docker/`(bootstrap.sh + compose;postgres + server);server `entrypoint.py` external-runner 模式。
  - OIDC 外接 KC:`OMNIGENT_AUTH_PROVIDER=oidc` + `OMNIGENT_OIDC_ISSUER/CLIENT_ID/CLIENT_SECRET/REDIRECT_URI/COOKIE_SECRET`(`omnigent/server/oidc.py:OIDCConfig.from_env`、`server/routes/auth.py`)。
  - 两层鉴权:`omnigent/server/permissions.py:check_session_access`(LEVEL_READ/EDIT/MANAGE/OWNER)+ policy engine(`runner/policy.py`、`server/routes/sessions.py:evaluate_policy`)。
  - host 隔离:`stores/host_store.py`((owner,name) 主键、`list_hosts WHERE owner`、host_id UNIQUE)、`server/routes/hosts.py`(get/launch owner 校验 403)、`server/routes/host_tunnel.py`(managed token → owner)。
  - managed host launch:`server/managed_hosts.py:launch_managed_host(owner=...)`;provider 经 YAML `sandbox:` 或 `ManagedSandboxConfig(launcher_factory=...)` 接缝;managed 需 oidc/header 认证(accounts 不行)。
- **可复用(备份分支 `dev-workspace-containerization` / tag `plan9-main-backup`)**:对话 UI(AgentChat/useSessionStream)、BFF omnigent 反代骨架、`omnigent_build.sh` + 镜像构建(已证可编译)、docker SandboxLauncher 雏形(若走自写 docker provider)。

## 技术选型理由
- **managed host(非 BYO)**:容器化 + 用户间强隔离 + 服务端锁 owner,贴 spec 的"沙箱隔离";BYO 是用户自带机器,不适合平台托管。
- **SDK harness(非 claude-native)**:容器/managed 场景原生、流式、无终端坑(上一轮实测 claude-native 容器内私有 mount-ns 卡死)。
- **fork-as-submodule(非 patch-queue)**:owner 要持续改 omnigent,fork 走正常 git 工作流,patch-queue 改一次重生成太痛。
- **官方 deploy/docker(非手搓)**:上一轮手搓 compose + 手动 host/launch_runner 是一切坑的根源。

## ★ DoR 自检(逐项三态:已决定 / 显式推迟+理由 / 待探查+探针+决策规则)
- [x] **1 范围与出口**:**已决定**。In=对话窗 + 多用户 KC + managed 沙箱 + fork 自编译;Out/推迟=所有数据访问(MCP/can()/catalog/文件终端/管线)→ 9b。可证伪验收见 spec SC + 隔离负向测试。
- [ ] **2 接口契约**:**部分待探查**。对外=Workspace 对话窗(第一个消费者=该 UI,**复用现有对话 UI**,等于已有低保真)。BFF↔omnigent 的 REST/WS 端点(建会话/发消息/SSE 流)以 omnigent openapi 为准,**探针 #2 实测端点/字段/流式事件钉死**(上一轮手搓的端点知识来自旧分支,需用官方 managed 流程复核)。错误形态:未认证→跳登录;无沙箱→明确报错。
- [x] **3 数据模型**:**已决定(复用 omnigent 自带)**。Conversation/Host/会话身份均 omnigent 原生,隔离不变量见上;我们不新增实体。
- [ ] **4 外部依赖事实**:**approach 已定 + 待探针实测(P1,关键)**。approach=**自写 docker SandboxLauncher 放我们 fork**(omnigent 无内置普通-docker provider;k8s/云/boxlite 不走,理由见「外层 provider」)。**探针 P1** 实测这条 docker 链路:server 经 DockerSandboxLauncher provision 隔离容器 host + SDK harness 起 agent + 流式回 SSE + 产品凭据注入。**决策规则**:跑通→采纳;跑不通→诊断修(SandboxLauncher 是我们 fork 里的代码,可改);实在不行→退 k8s pod(需先上 k8s)或 BYO(回 design)。**这是 9a 最大风险,plan 首个 Task。**
- [x] **5 行为·边界·并发·威胁**:**已决定**。边界(无沙箱/中断/未登录/伪造/凭据缺失)见 spec Edge Cases;红线=隔离负向测试(见授权与安全);并发=每用户独立会话+沙箱。
- [x] **6 NFR**:**已决定**。parity(fork 自编译 same-bits)、流式(SDK delta)、隔离(omnigent owner)、secret(env)、拓扑(ECS + 我们 docker 拉沙箱〔落地见 #4〕)。
- [ ] **7 验收与测试策略**:**plan 阶段产出 runbook**。可证伪:两用户各自登录对话、互不可见、agent 各自隔离沙箱、改 omnigent 一行重编译生效。测试分层:BFF 反代单元/集成、隔离负向测试、手动 runbook(双用户 live + fork 改码生效)。
- [ ] **8 关键决策留痕**:**待写**。ADR-026(本 plan:managed host + KC OIDC 多用户 + fork 自构建模型C + SDK harness + 对话窗 MVP scope + 否决 BYO/patch-queue/claude-native)。

> **DoR 结论**:8 项中 5 项已决定;#2(契约)、#4(managed 沙箱落地)、#7(runbook)= 待探查/plan 产出,**均带探针 + 决策规则,无静默 TBD**。#4 是地基风险,定为 plan 首个探针 Task(探查优先)。**进 writing-plans 前需 owner 过门 + ADR-026 落定。**
