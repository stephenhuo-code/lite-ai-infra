# ADR-026: omnigent 集成(Plan 9a)—— managed host + KC OIDC 多用户 + fork 自构建 + 对话窗 MVP

- 状态:**Proposed(2026-06-28)**。owner 已拍定方向;**正式 Accept 留待 DoR 过门 + 探针 P1 实跑确认**(官方 managed 链路在我们自托管 docker 上跑通 + SDK harness 流式)。
- 决策人:owner
- 关联:S1 出口④ 降级项 **Plan 9 拆分为 9a(本 ADR,omnigent 集成 + 对话窗)+ 9b(dev workspace 全貌)**。承接 [ADR-025](./ADR-025-keycloak-organizations-as-enterprise.md)(KC 企业化)、[ADR-022](./ADR-022-ci-on-aliyun-ecs.md)(ECS)。遵循 constitution §5.3(parity)、§1.6(隔离)、§5.2(secret 不入库)。
- 调研:omnigent 源码级调研(2026-06-28,三面:官方容器部署 / 多用户 OIDC + 策略引擎 / host 归属隔离),结论见 [design.md 依赖与引用](../superpowers/plans/2026-06-28-omnigent-integration/design.md#依赖与引用)。spec/design:[`2026-06-28-omnigent-integration/`](../superpowers/plans/2026-06-28-omnigent-integration/)。

> **背景**:Plan 9(Dev Workspace = omnigent 集成)第一轮失败——把 omnigent 当可改的内部库**手搓**(手动 `omnigent host`、手动 launch_runner、私改内部、单用户),在容器化/多用户/claude-native 终端上反复撞墙。复盘:**omnigent 是成熟产品,容器/多用户/流式它都解决了,该按它官方方式当独立服务用**。第一轮工作已重置(回 clean main 0c7d4b6;旧工作存备份分支 `dev-workspace-selfbuild`/`dev-workspace-containerization` + tag `plan9-main-backup`)。本 ADR 是按官方方式的重做,且把 Plan 9 拆成 9a/9b 收窄 scope。

## Decision

### 1. Plan 9 拆 9a / 9b
- **9a(本 ADR)**:只做 omnigent 集成 + Workspace **对话窗**(每用户和 agent 对话)。**无任何数据访问**。
- **9b(下个 plan)**:dev workspace 全貌(左树 catalog/git、文件/终端、MCP 数据工具 + 企业/owner `can()` 承重墙、管线、持久化)。

### 2. 按 omnigent 官方方式部署(不手搓)
- 用 `deploy/docker/` 官方 compose:postgres + server 镜像(`--target runtime`,external-runner 模式——server 只协调)。
- host = **managed**:server 按用户/会话 provision 隔离沙箱(`--target host` 镜像),owner 服务端锁定 + launch token,用户凭据不进沙箱。
- **外层 provider = docker(自写 `DockerSandboxLauncher`,提交进我们 fork)**:omnigent 无内置普通-docker managed provider(boxlite=微VM 需 KVM、modal/e2b=云 SaaS、kubernetes=k8s pod),但有 launcher-factory 接缝;我们自托管用 docker → 自写最小 docker launcher(`docker run` host 容器 + 注入 token/凭据 + `docker rm` 回收)。**k8s/云/boxlite 不走**(k8s 仅未来若迁 k8s 备选)。
- **两层沙箱**:外层=managed host 容器(用户间隔离承重);内层=agent `os_env.sandbox`,9a 取 `none`(靠外层 + 无数据访问),9b 接数据后按需上 bwrap。
- **不再**手动 `omnigent host` / 手动 launch_runner / 私改内部接线。

### 3. 多用户:KC OIDC(BFF 认证)+ omnigent header-trust + omnigent 鉴权(资源 + 行为)

> **探针补漏修订(2026-06-29,T3 前)**:P1 探针跑的是 `AUTH_ENABLED=0`,OIDC env 名从未实测。读 fork 源后定论:omnigent `AUTH_PROVIDER=oidc` 会让 omnigent **自己**对 KC 再跑一遍 OIDC、自颁 `ap_session` cookie ⇒ 浏览器二次登录并持有 omnigent token,**撞 FR-008(前端不持 omnigent token)+ 双登录**。改采 omnigent **header-trust 模式**(`OMNIGENT_AUTH_PROVIDER=header` + `OMNIGENT_AUTH_HEADER=X-Forwarded-Email`,fork 原生支持、managed 兼容):**KC OIDC 仍在,但落在 BFF**(已实现),BFF 用已认证 KC 会话解出身份 → 注入 `X-Forwarded-Email` 给 omnigent、剥客户端伪造的同名头;omnigent 信任该头。**正是本 plan Task 4「身份注入+剥伪造头」**。
> 影响:① 单次登录;前端只持 BFF 会话(满足 FR-008)② omnigent 不可被客户端直达 ③ **不需在 KC realm 注册 omnigent OIDC client**(plan Task 2 Step 1 取消,非静默砍——见 plan 注)。决策人=owner 授权 AI 拍板(2026-06-29)。

- **KC=认证(在 BFF)**;omnigent=**header-trust**(信任 BFF 注入的已认证身份头)。
- **omnigent=鉴权两层**:permission store(谁能访问某会话/host)+ policy engine(已授权用户的 agent 行为)。
- host 用户间隔离:`(owner,name)` 主键 + owner 过滤 + 跨用户 host_id 劫持挡(原生)。一用户可多 host。

### 4. harness = claude-native + 订阅(P1 实测回正)

> 早稿写 claude-sdk + 产品 key(误判 claude-native 容器内不行/不流式)。**P1 探针推翻**:claude-native 在官方 managed docker 容器里正常 + 流式 + 用订阅真回复。回正:

- managed 沙箱内 agent 用 **claude-native harness**(官方 managed 流程里终端正常,非手搓那次的坑)。
- **凭据 = 单一共享 claude 订阅 token**(`CLAUDE_CODE_OAUTH_TOKEN`,server 经 `sandbox.docker.env: [CLAUDE_CODE_OAUTH_TOKEN]` 注入所有沙箱)。**零 API 额度**(用订阅)。**坑**:勿同时注入 ANTHROPIC_API_KEY(会触发 apiKeyHelper 与订阅 token 冲突)。
- **流式**:executor `supports_streaming()=False`,但 transcript forwarder 旁路把 MessageDisplay 增量 POST `external_output_text_delta` → server 转 `response.output_text.delta` 走 SSE(best-effort,消息块级,时序滞后于 completed)。前端读流**别在 completed 停**。
- **per-user 订阅推迟**(owner 决策 (b)):9a 全员共用一个订阅 token;**多用户隔离仍成立**(每用户独立 managed 沙箱/会话,仅模型 token 共享)。per-user(vault 设置页 + fork-patch 按 owner 注入)留 9a 末尾 / 9b。
- **claude-sdk + 产品 key** 作备选(要逐 token 细粒度流式时;实测链路通但需有额度 key)。codex-native + codex 订阅机制对称,可后续加。

### 5. omnigent 自维护 = 模型 C(fork 作 submodule,自编译)
- fork omnigent 到我们自己的仓 → 在 fork 里正常 commit 改 → lite-ai 把 fork 当 submodule 钉 commit → `scripts/omnigent_build.sh` 自编译 server+host 镜像。
- 三层 parity:dev 本地 build / CI build+push registry / prod pull same-bits;不依赖上游预构建。定期 merge upstream。

### 6. 客户端复用现有 UI,经 BFF 反代
- 控制台新增 Workspace 对话窗(复用现有 React 对话组件,可从备份分支捞),经 BFF 反代 omnigent REST+WS;前端不持 token;BFF 剥伪造头 + omnigent 不可直达。

## Consequences
**正面**:scope 收窄(只对话窗)→ 可控;按官方方式 → 不再撞 omnigent 内部坑;KC OIDC + omnigent 隔离原生;fork 自编译保 parity + 可持续改码;9a 无数据访问 → 无承重墙风险,9b 再建。

**负面/风险**:① managed 沙箱在**自托管 docker** 上的 provider 未定(内置 boxlite 需 KVM、云 provider 是 SaaS)→ 探针 P1 钉死(可能自写 docker launcher,旧分支有雏形)② SDK harness 需产品级模型凭据(成本 + secret 管理)③ omnigent alpha,fork 后需定期 merge upstream ④ 两套后端(我们服务 + omnigent)运维。

## 否决的备选
- **手搓集成(上一轮)**:手动 host/launch_runner + 私改内部 → 一切坑的根源,已重置。
- **BYO host**:用户自带机器,不适合平台托管多用户隔离;managed 更贴。
- **claude-sdk + 产品 key 作 9a 默认**:虽逐 token 流式更细,但要有额度的 API key;owner 要用订阅 → 9a 走 claude-native + 订阅,claude-sdk 留备选。(早稿曾否决 claude-native,P1 已推翻——见决策 4。)
- **patch-queue(旧思路)**:改一次重生成 patch、体验差;owner 要持续改 → 改用 fork-as-submodule。
- **per-user 个人订阅(9a 就做)**:omnigent managed 沙箱凭据 server 全局注入,per-user 需我们加 vault + fork-patch 按 owner 注入;owner 决策 (b) 9a 先用共享订阅,per-user 推迟。
- **9a 就把数据工具/承重墙做了**:scope 蔓延正是上一轮失败因;严格推迟 9b。

## 探针结论(2026-06-28~29,已跑通)
- **P1 ✅ 跑通**:官方 managed 链路在自托管 docker 上端到端——server 经自写 `DockerSandboxLauncher` provision 隔离容器 host + claude-native 起 agent + **用共享 claude 订阅真回复** + **流式 `response.output_text.delta`** + 用户隔离。详见 [spike P1](../superpowers/plans/2026-06-28-omnigent-integration/spikes/P1-managed-docker.md)。
  - 验证过的 fork 改动(Phase 1 提交进 fork):`DockerSandboxLauncher`(+ `run_background` 覆写修内联 env)、provider `docker` 注册、Dockerfile runtime 加 docker CLI。
  - 坑钉死:managed create = JSON body `{agent_id, host_type:"managed"}`;server 挂 docker.sock;只注订阅 token(勿混 ANTHROPIC_API_KEY);前端读流别在 completed 停。
- **P2(契约)**:建会话/发消息/SSE 端点已在 P1 实测钉死(见 spike);BFF 反代按此实现。
