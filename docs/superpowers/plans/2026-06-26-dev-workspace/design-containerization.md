# Design(设计):Dev Workspace 全容器化 + per-user managed host

> 设计层(HOW)。承接 [ADR-027](../../../adr/ADR-027-dev-workspace-full-containerization.md)(决策)+ [ADR-026](../../../adr/ADR-026-dev-workspace-omnigent.md)(omnigent 后端/自构建/承重墙)。需求见 [`spec.md`](./spec.md)(Dev Workspace 总 spec);本文聚焦"全容器化 + 多用户 host + 订阅凭据 + 流式"这一架构演进。过 DoR 单门后才进 tasks。

## 架构

### 模块分层 / 隔离边界(目标拓扑,全容器化)

```
┌─ 容器边界(dev=prod 同镜像) ───────────────────────────────┐
│  omnigent server        :8900  header-auth 多用户              │
│  ──(server-launch)──▶ per-user managed host(每用户一个容器)   │  ← 强隔离边界
│        · 携带该用户 claude/codex 订阅凭据(注入)               │
│        · 一 host 多 session                                    │
│        └ runner(每会话动态派生 · 绑 session owner · sandbox=none〔推迟〕) │
│              └ harness: claude-native / codex-native(改 spec 即切) │
│  BFF/gateway :8090 · 我们的 MCP :8910 · 前端(dist)             │
└────────────────────────────────────────────────────────────┘
承重墙(不变):BFF 铸令牌 → MCP 校验→Context→can() → 数据(与 omnigent 身份正交)
```

- **新增/改动**:① server native-host → 容器化 host(同镜像)② 单用户 → header-auth 多用户 ③ 引入 per-user managed host 编排 ④ 新增 per-user 凭据库(捕获/加密/注入)⑤ 前端 items 轮询 → 增量流式渲染。
- **依赖方向(不破分层)**:前端 → BFF → omnigent(REST/WS);agent(Claude Code/codex)→ 我们的 MCP(令牌 URL)→ 数据。BFF 是唯一信任边界,omnigent 不可被客户端直达。
- **与宪法一致**:§5.3 parity(dev=prod 同镜像,取代 native 源码 host);§1.6 企业硬隔离(per-user host 容器 + MCP can());§2.4 can() 单一授权出入口(承重墙不变);§5.2 secret 不入库(订阅凭据加密)。

## 核心流程 / 协议

### 流程 A:用户 onboarding —— 订阅凭据捕获

1. 用户在设置页发起"连接模型订阅"。
2. 引导用户本地执行 `claude setup-token`(产 OAuth token)/ `codex login`(产 `~/.codex/auth.json`);把产物提交给产品(粘贴 token / 上传 auth.json)。
3. 产品**加密存储**(per-user 密文,§5.2),不回显、不入日志。
4. 状态:该用户"claude 已连接 / codex 已连接"。无凭据 → 不能起对应 harness 的会话(明确报错,不静默)。

### 流程 B:建会话 —— 起 per-user host + 每会话 runner

1. 前端建会话 → BFF 从 BFF 会话解出 `(sub, 企业, 角色)`(不信请求体)。
2. BFF/server 检查该用户是否已有在线 managed host;**无则 server-launch 一个 per-user managed host 容器**,启动时注入该用户的订阅凭据(env `CLAUDE_CODE_OAUTH_TOKEN` / 写 `CODEX_HOME/auth.json`)+ managed host token。
3. BFF 建 bundled 会话(上传 agent spec,harness=claude-native/codex-native)→ 铸每会话令牌 → register 我们的 MCP(令牌化 URL)。
4. `launch_runner(host=该用户 host, session_id, workspace=该用户 host 内 per-session 目录)` → host spawn runner(绑 session owner)。

### 流程 C:发消息 —— 流式渲染

1. 前端 → BFF → omnigent `POST /events`;agent 推理(用注入的订阅凭据)。
2. **流式**:codex-native 逐 token / claude-native 段落级 delta → SSE `/stream`(`output_text.delta` / `external_output_text_delta`)。
3. 前端订阅 SSE 增量拼接渲染 + `/items` 兜底对账(去重)。数据工具调用经承重墙(令牌→Context→can())。

## 数据模型

- **UserModelCredential**(新):`user_id`(不透明)→ `{claude_oauth_token?, codex_auth_json?}` **密文** + `updated_at` + 各 provider `connected: bool`。**不变量**:明文绝不落库/落仓/落日志(§5.2);仅在 launch host 时解密注入。状态:`未连接 → 已连接 →(轮换)→ 已连接 /(吊销)→ 未连接`。
- **ManagedHost**(omnigent 既有,`hosts` 行):`host_id`(持久)+ `owner` + launch-token digest + expiry + sandbox 代 + `configured_harnesses`。**不变量**:owner 绑定;sandbox 死了重建保持 host_id(session 绑定存活)。证据 `omnigent/server/managed_hosts.py:1-30`。
- **Session↔Host↔Runner 绑定**(omnigent 既有):`conversation.runner_id`(原子 CAS 绑定)+ session.owner/enterprise。**不变量**:一 session 绑一 runner;双 owner 检查。证据 `omnigent/server/routes/hosts.py:434-443,580-603`。
- **每会话令牌**(承重墙,既有):`token→(sub, 企业, 会话)`,Fernet,WS_TOKEN_KEY 跨进程同值。

## 授权与安全

- **承重墙(不变,§2.4/§1.6)**:数据访问只经我们 MCP 工具,每次 `can()`(企业 + owner)。容器化/多用户**不改**这条;agent 即使放飞,只能以会话绑定的那一个用户、经我们暴露的工具、被 can() 拦。
- **header-auth 信任义务(ADR-026 §3)**:BFF MUST 剥离客户端伪造身份头;omnigent server MUST 不可被客户端直达。
- **managed host token**:`X-Omnigent-Host-Token`,server 签发、短期、绑 host_id+owner。证据 `omnigent/host/identity.py:27-36`、`omnigent/server/routes/host_tunnel.py:121-196`。
- **订阅凭据(§5.2)**:per-user 加密存储;仅 launch host 时解密注入容器;不回显/不日志。
- **威胁与红线(本演进的负向测试)**:① 伪造身份头被剥离(BFF)② 跨用户:A 的令牌/会话拿不到 B 的数据(can() deny)③ 凭据明文绝不出现在库/仓/日志/SSE ④ omnigent 不可直达绕过 BFF。
- **sandbox=none 的已接受弱点(显式推迟,ADR-027 §4)**:同一用户多 session 共享其 host 文件系统;agent 能读到该用户 host 内注入的订阅凭据。均在**该用户自己边界**内(强边界=per-user 容器)。prod 硬化上 `linux_bwrap`。

## 非功能(NFR)

- **dev/prod parity(§5.3,本演进的核心目标)**:dev 与 prod 跑**同一套 omnigent 镜像**(server + host,经 ADR-026 三层 same-bits)+ 同架构(容器化 host + managed host + header-auth)。native 源码 host 退役为"改 omnigent 源码后本地快验"的临时手段。
- **并发 / 可靠性**:每用户一 host、一 host 多 session;runner 派生无硬上限(受 host 容器 FD/内存约束);runner crash 由 host watcher 上报(`omnigent/host/connect.py:804-806`)。
- **安全**:订阅凭据密文(§5.2);每会话令牌 TTL + 吊销;managed host token 短期。
- **性能 / 规模**:流式首 token 延迟(目标见 spec SC);per-user host 冷启动延迟(首会话需 launch host)——可接受阈值见 spec;超阈值登记 vNext。
- **部署拓扑**:aliyun ECS(ADR-022);per-user host 容器由 omnigent server 经 provider 编排(**provider 待探针 P1**)。

## 依赖与引用

- **决策(ADR)**:[ADR-027](../../../adr/ADR-027-dev-workspace-full-containerization.md)(本演进)、[ADR-026](../../../adr/ADR-026-dev-workspace-omnigent.md)(omnigent 后端/自构建/承重墙)、[ADR-022](../../../adr/ADR-022-ci-on-aliyun-ecs.md)(ECS)、[ADR-024](../../../adr/ADR-024-owner-based-dataset-ownership.md)(can())、[ADR-025](../../../adr/ADR-025-keycloak-organizations-as-enterprise.md)(KC org)。
- **omnigent 源码事实(2026-06-27 四面 research,file:line)**:
  - host 镜像:`third_party/omnigent/deploy/docker/Dockerfile`(`--target host`,含 claude/codex CLI + bwrap + tmux);`scripts/omnigent_build.sh:25-26`(同时 build server+host)。
  - host 认证:`omnigent/host/identity.py:27-36`(`OMNIGENT_HOST_TOKEN`/`X-Omnigent-Host-Token`);`omnigent/host/connect.py:1373-1418`;`omnigent/server/routes/host_tunnel.py:121-196`。
  - managed host:`omnigent/server/managed_hosts.py:1-30,177-187`(owner 绑定、sandbox 重建、provider 注记)。
  - runner 派生/授权:`omnigent/host/connect.py:708-825`(spawn + env allowlist);`omnigent/server/routes/hosts.py:405-666`(双 owner 检查 + CAS);`omnigent/runner/identity.py:98-115`(token 绑 runner_id);`omnigent/runner/policy.py:109-200`(policy gate)。
  - sandbox:`omnigent/inner/datamodel.py:462-658`(`os_env.sandbox.type` 全集);`omnigent/inner/bwrap_sandbox.py`(linux_bwrap 权限需求)。
  - harness/model:`omnigent/model_catalog.py:50-83`(harness 全集);`omnigent/spec/types.py:486-617`(`executor.config.harness`/`auth`);`omnigent/codex_native.py`(`_resolve_codex_auth_source` 的 managed-credentials 接缝)。
  - 流式:`omnigent/claude_native_bridge.py:1089`(MessageDisplay hook 无条件装配)+ `claude_native_forwarder.py:783-801,3069-3171`(message_deltas.jsonl → `external_output_text_delta`,**段落级**);`codex_native_forwarder.py:1876-1881`(host auto-create subscribe race)+ `2684-2710`(live delta 逐 token);实证 dev native 路径 delta 未达 SSE。

## 技术选型理由

- **容器化 host(非 native 源码)**:唯一能保证 §5.3 parity + 多用户 + 版本一致的形态;omnigent 已提供 host 镜像,几乎零额外造。
- **per-user managed host(非单共享)**:把强隔离边界落在容器=每用户;让每 host 携带该用户自己的订阅凭据,绕开"多用户共享一个产品凭据"难题;避开流式 race。
- **native harness + 个人订阅(非 SDK+网关)**:owner 决策先用订阅;native harness 改 spec 即切,零凭据采购。代价 = claude 流式仅段落级、凭据绑个人;SDK+网关留 vNext。

## ★ DoR 自检(进 tasks 前过门;逐项三态:已决定 / 显式推迟+理由 / 待探查+探针+决策规则)

- [x] **1 范围与出口**:**已决定**。In:全容器化 host + header-auth 多用户 + per-user managed host + 每会话 runner + 订阅凭据流 + 增量流式渲染。Out/推迟:bwrap 沙箱(vNext 硬化)、SDK harness+产品网关(vNext)、跨节点 host 池调度(vNext)。出口:取代 native 源码 host 技术债,恢复 §5.3 parity。
- [x] **2 接口契约**:**已决定(复用既有)**。omnigent REST/WS(ADR-026 既有,BFF 反代);承重墙令牌 URL(既有);**新增对外面**=用户"连接订阅"设置页(第一个消费者=该 UI,需低保真:粘贴 token / 上传 auth.json + 连接状态)。错误形态:无凭据起会话 → 明确 4xx「未连接 <provider> 订阅」。纯内部的 managed-host launch/注入无对外契约,豁免。
- [x] **3 数据模型**:**已决定**。新增 `UserModelCredential`(密文,不变量=明文不落库/仓/日志,状态机:未连接↔已连接);复用 omnigent `hosts`(managed)/`conversation.runner_id` 绑定 + 每会话令牌。标识用不透明 user_id/host_id/session。
- [ ] **4 外部依赖事实**:**待探查(P1)**。omnigent 在**我们 infra(docker/k8s on ECS)**上 server-launch per-user managed host 的 provider 未实证(现成 provider 多为云沙箱 Modal/Daytona/CoreWeave/OpenShell)。探针 P1 + 决策规则见 ADR-027「待探针确认」。其余源码事实已成文(本文「依赖与引用」file:line)。
- [x] **5 行为·边界·并发·威胁**:**已决定 + 一处推迟**。错误/降级:无凭据→报错不静默、host 冷启动失败→回退报错、runner crash→watcher 上报。并发:每用户一 host 多 session、runner CAS 防竞争。威胁/红线:伪造头剥离、跨用户 can() deny、凭据明文不外泄、omnigent 不可直达(负向测试)。沙箱越权防护=**显式推迟**(sandbox=none,理由见上)。
- [x] **6 NFR**:**已决定 + 一处待探查**。parity(同镜像,核心达成)、安全(凭据密文§5.2 / 令牌 TTL / host token 短期)、隔离不变式(per-user 容器 + MCP can())、部署拓扑(ECS + provider〔P1〕)。流式延迟/host 冷启动阈值入 spec SC。
- [ ] **7 验收与测试策略**:**待补(plan 阶段产出 runbook)**。可证伪验收:dev 用容器化 host 多用户登录 → 两个不同用户各自会话互不可见、各用自己订阅、回复流式增量出现。测试分层:单元(凭据加解密/注入构造/can())、集成 seam(BFF↔omnigent REST/WS、MCP 令牌)、手动 runbook(全容器化起栈 + 双用户 live)。DoD:负向测试(威胁红线)全绿 + parity 自检(dev/prod 同镜像 tag)。
- [x] **8 关键决策留痕**:**已决定**。[ADR-027](../../../adr/ADR-027-dev-workspace-full-containerization.md) 含决策 + 否决备选(native host / SDK+网关 / 单共享 host / 现在上沙箱)+ 两探针。承接 ADR-026。

> **DoR 结论**:8 项中 6 项已决定、2 项(#4 外部依赖、#7 测试/runbook)分别为「待探查+探针 P1」与「plan 阶段产出」——**无静默 TBD**。流式(P2)、provider(P1)两探针带决策规则。**进 writing-plans 前需 owner 过门拍这 8 项**(机器自评不算),探针 P1/P2 建议作为 plan 的首批 Task(探查优先)。
