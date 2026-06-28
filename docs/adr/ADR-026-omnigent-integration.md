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

### 3. 多用户:KC OIDC(认证)+ omnigent 鉴权(资源 + 行为)
- omnigent `AUTH_PROVIDER=oidc` 接我们 Keycloak(标准 OIDC,原生零改码)。
- **KC=认证**;**omnigent=鉴权两层**:permission store(谁能访问某会话/host)+ policy engine(已授权用户的 agent 行为)。
- host 用户间隔离:`(owner,name)` 主键 + owner 过滤 + 跨用户 host_id 劫持挡(原生)。一用户可多 host。

### 4. harness = SDK(非 claude-native 终端)
- managed 沙箱内 agent 用 **SDK harness(进程内,原生流式,容器友好)**。
- 否决 claude-native(tmux 终端):上一轮实测在容器内撞私有 mount-ns / 首次 onboarding,卡死无回复。
- 凭据:managed 沙箱用 **产品级凭据**(API key/网关,经 server 注入沙箱 env),与 SDK harness 一致;个人订阅留 9b+ 评估。

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
- **claude-native 终端 harness**:容器内私有 mount-ns/onboarding 坑,实测卡死;改用 SDK harness。
- **patch-queue(旧 ADR-026 思路)**:改一次重生成 patch、体验差;owner 要持续改 → 改用 fork-as-submodule。
- **个人订阅凭据(每用户自己的)**:omnigent managed 沙箱凭据是 server 注入(全局),per-user 个人订阅无原生接缝且与 SDK harness 不合;9a 用产品级,个人订阅留后评估。
- **9a 就把数据工具/承重墙做了**:scope 蔓延正是上一轮失败因;严格推迟 9b。

## 待探针确认(进 writing-plans 前 / plan 首个 Task)
- **P1(地基,关键)**:官方 managed 链路在**我们自托管 docker** 上跑通——server provision 隔离沙箱 + SDK harness 起 agent + 流式回 SSE + 产品凭据注入。决策规则:内置 provider(k8s 等)可用→用之;否则自写最小 docker SandboxLauncher(launcher-factory 接缝);都难→评估 BYO 退路(回 design)。
- **P2**:BFF↔omnigent 的建会话/发消息/SSE 流端点与事件(用官方 managed 流程复核,钉死契约)。
