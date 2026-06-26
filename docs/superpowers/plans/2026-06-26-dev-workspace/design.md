# Design — Dev Workspace(Plan 9):agent 数据开发台

> HOW。需求(WHAT/WHY)见 **spec.md(owner 待写)**。地基/外部依赖决策落 **[ADR-026](../../../adr/ADR-026-dev-workspace-omnigent.md)**。外部依赖事实见 **[omnigent spike RESULTS](../../spikes/2026-06-26-omnigent-feasibility.md)**(源码级实测)。
> 关哪个出口:S1 出口④ 的降级项 Plan 9 —— 从"code-server + Remote-SSH 半天版"**升级为 agent 工作台**(owner 2026-06-26 重定义)。

## 一句话
基于数据目录的数据集做**数据探查 + 数据管线开发(Data-Juicer + Python)**的 **agent 工作台**:我们自建 React 前端(左树 + agent 对话/文件/终端),后端用 **omnigent**(Apache-2.0 self-host)作 agent runtime + 沙箱,数据能力经**我们的 MCP 工具**喂给 agent(can() 按企业/owner 把关)。

## 架构
> 可控链路全图见 **[assets/control-chain.svg](./assets/control-chain.svg)**(用户 → agent 会话 → 数据集 + 三个控制点)。
```
我们的 React19 控制台 ── 新增「Dev Workspace」页(自建 UI,经 API 驱动 omnigent;前端不持 token)
  左树:工作目录(持久化对象存储)+ catalog(我们的 API)+ git 树
  右侧:agent 对话 + 文件查看(monaco)+ 终端(xterm)
        │  REST + WS
        ↓
  我们的 BFF(★单一信任边界)── 反代 → omnigent server(REST + WS)
        ├─ header-auth 注入身份头(MUST 剥离客户端伪造的同名头);omnigent 不直达
        └─ 会话创建时铸「每会话令牌」 token→(sub, 企业, 会话),并据此注册我们的 MCP server
        ↓
  omnigent ②-⑥(自托管 docker,预构建镜像):Server/Host/Runner(每会话进程 + 沙箱)/Harness(claude-sdk)/policy
        │  agent 调工具 ↓(http transport,URL 内嵌每会话令牌)
  我们的 MCP server:工具 = 读 catalog 数据集 / 取 OSS / 跑 DJ+python / 工作目录+git
        └─ 校验令牌 → 还原 KC ctx → 每次 can()(企业硬隔离 + owner)→ 数据集
```
**复用 vs 自建**:omnigent 给 agent runtime/沙箱/harness/policy(难造,直接用);我们自建 = 前端 UI + BFF 反代 + **我们的 MCP 工具**(把"数据探查/管线开发"暴露给 agent)。client 自建(非 iframe/非 React-island 嵌入)—— 因 React19/RR7 与 omnigent embed 期望 React18/RR6 鸿沟(见 spike RESULTS ①)。

## 授权三分层 + 红线(ADR-026 核心)
| 关注 | 谁管 |
|---|---|
| **认证(你是谁)** | **Keycloak**;omnigent 前门用 **header-auth**(BFF 注入身份头),非 omnigent OIDC —— 见"前门认证"|
| **租户/数据授权(能否碰这份企业数据)** | **我们 `can()`(→Cerbos),在 MCP 工具内 —— 绝不外包 omnigent**(宪法 §2.4 单一出入口 / §1.6 企业硬隔离)|
| **agent 行为治理(shell/tool/cost/working_dir/危险操作 ASK)** | **omnigent PolicyEngine**(自带,我们没有,直接用)|
| **会话协作(谁能 view/edit/run 某会话)** | **omnigent session permissions**(限我们租户内)|

**红线**:租户/数据隔离不外包给 omnigent policy —— omnigent 的 policy 作用对象是 agent 动作,不懂我们的企业/owner/catalog 模型。
**Cerbos 与 omnigent policy 正交、不一起实现**:MCP 工具是接缝,Cerbos 落地把工具内 `can()` 换 Cerbos 即可,不碰 omnigent。

### 数据集受控链路(token 绑定 + can())—— 本设计承重点
omnigent 的每会话 MCP 注册体**只有** `name/transport/command/args/url`,**无 header/env 转发槽**(spike 实证)→ omnigent **不会**把用户身份转发给我们的 MCP 工具。故"数据集受控"**必须由我们自己绑定**,与前门 OIDC/header 无关:
1. **BFF 铸每会话令牌**:会话创建时,BFF(握 KC 身份)生成短时、不透明、每会话令牌,存映射 `token → (sub=owner, 企业 alias, 会话)`。
2. **令牌即绑定**:用 **http transport** 把我们的 MCP server 注册给该会话,URL 内嵌令牌(`https://<mcp>/s/<token>/mcp`)。omnigent/agent 只知本会话这一个 URL。
3. **每次调用 can()**:agent 调工具 → MCP server 校验令牌 → 还原出与控制台后端**同形的** `Context(企业, user=sub, role)` → 跑**同一个** `can()`(企业硬隔离 + owner,ADR-024)。
- **不变式**:agent 即使放飞,也只能①以该会话绑定的**那一个用户**身份、②只经我们暴露的**那几个工具**、③每次被 `can()` 拦。**不依赖信任 omnigent 转发身份**(对 alpha 第三方=防御纵深)。

### 前门认证(header-auth,非 OIDC)
- omnigent 认证为纯 env 配置(`OMNIGENT_AUTH_PROVIDER=header`/`OMNIGENT_AUTH_HEADER`,spike 实证),**零源码改动**。BFF 认证用户(KC)后注入身份头给 omnigent(供 omnigent 自身会话 owner/policy/协作用)。
- **为何非 OIDC**(理由修正,非"OIDC 差"):① 我们是"自建 client + BFF 反代"架构,BFF 为单一信任边界,header 天然契合(前端不持 token、omnigent 不直达);② OIDC 会让 omnigent 自跑登录(浏览器直连 + `__Host-` cookie),与 BFF 单边界重复/冲突;③ **OIDC 的"原生 KC 身份"到不了我们的 MCP 工具(无转发槽),对数据集受控零增益**。若改为前端直连 omnigent(不走 BFF),OIDC 才成自然选择。
- **header 模式强制义务**:BFF MUST 剥离客户端传入的同名身份头(防伪造);omnigent server MUST 不可直达(仅经 BFF)。

### 授权可扩展性:group + role / Cerbos 演进(沿 ADR-011 / ADR-025 / ADR-026 §4)
未来"organization group + per-group role"来时,**链路拓扑、令牌机制、omnigent、MCP 注册全不变**,只动既有缝:
| 扩展点 | v1 现在 | 加 group+role 后 | 改的位置 |
|---|---|---|---|
| 令牌映射 | `token→(sub, 企业, 会话)` | `token→(sub, 企业, 会话, groups[], roles[])` | BFF 铸令牌多带 claim(本就握完整 KC token)|
| Context 重建 | `parse_context(sub, organization, realm_roles)` | 再读 org-group / per-group-role claim | `parse_context`(ADR-025 已留 seam + group 回归路径)|
| 授权判定 | `can()`=企业 + owner | `can()` 内换 **Cerbos**:principal.group/role × resource 策略 | `can()` 实现,**调用点 `can(ctx,action,res)` 不变**|
- **owner(sub)与 group 共存**:owner 是一个 principal 属性,group 是另一个,Cerbos 一起算(如"数据集 X 共享给 `team-research`/`editor`")。agent 路径**自动**继承 group+role 授权,因为走同一道 `can()` 闸(§2.4)。group 主体来源(KC group / Organization Groups / Cerbos 自管)实现时定。

## 隔离(三道,协同)
1. **BFF 身份**:KC 会话(前端不持 token)。
2. **omnigent 沙箱 + working_dir policy**:agent 代码执行钉死在本 owner 工作目录(bwrap;working_dir 内置 policy 强化)。
3. **我们的 MCP 工具 can()**:数据访问(catalog/OSS)限企业/owner —— agent 只能经我们的工具碰数据。
- 工作目录按 owner 隔离;企业硬隔离不变。

## 能力(MVP)
基于数据目录的数据集:
1. **数据探查**:agent 经 MCP 读数据集 schema/采样/统计(对 Lance/webdataset)。
2. **管线开发**:agent 写并跑 **DJ recipe**(复用现有 `pipelines/data_prep/recipe.py`/`.dj-venv`/`runner.py`)+ **Python 代码**(沙箱内);产物可注册回 catalog(复用 catalog-driven 注册)。
3. **工作目录 + git**:文档/脚本版本管理(git tree 在左树)。

## 组件清单
- 前端:`frontend/src/pages/DevWorkspace.tsx`(+ 左树/chat/terminal/file-viewer 子组件),驱动 omnigent REST/WS。
- BFF:`services/gateway/bff/` 加 omnigent 反代(REST + WS proxy,身份注入)。
- **我们的 MCP server**(新):`services/dev_workspace_mcp/`(或并入现有服务)—— catalog/OSS/DJ/python/git 工具,内调 `can()`。
- omnigent:`deploy/dev/` 加 omnigent docker compose。**部署形态 = 预构建镜像,不 fork 改源码**:`ghcr.io/omnigent-ai/omnigent-server`(+ runner 用 `omnigent-host`);认证/UI/数据工具全经配置或 API,无须改码(spike 实证)。**钉 `:vX.Y.Z` 或 `:sha-<short>`(不用 `:latest`),prod 可镜像到自有 registry**(供应链 + 版本钉定)。认证用 `OMNIGENT_AUTH_PROVIDER=header` 等 env。
- 模型:harness 用 claude-sdk(订阅/API key,env 注入,§5.2)。

## 范围 / 序(epic)
- **Task 0 探针(docker 实跑,探查优先)**:本地起 omnigent(预构建镜像 compose)→ ① **header-auth** 模式下 BFF 注入身份头被 omnigent 接受(login 通)② **http transport MCP server(URL 内嵌令牌)被 agent 调用**且令牌还原 ctx 成功;核验有无 header/env 转发旁路(若有,优先 header 带令牌而非 URL 带令牌,避免入日志)③ 沙箱 + working_dir 限到工作目录;对象存储工作目录 ↔ 沙箱本地盘挂载/同步形态 ④ BFF 能反代 REST+WS。**带退化规则**(若某项不成,记录 + 调整集成形态)。
- 后续 Task:BFF 反代 / 我们的 MCP 工具(catalog→DJ→python→git,逐个 TDD)/ 前端(左树 + chat + terminal + file viewer)/ 隔离负例测试 / 图形 runbook。

## 留待 spec / Task0 钉死(诚实标注,非缺口)
- ~~**工作目录存储形态**~~ **已定(owner 2026-06-26)**:**对象存储为底、按 workspace 为单位持久化隔离**(如 `<企业>/{user}/workspace/<ws>/`),agent 默认授权访问本 workspace 目录;git **仅本地**(远端 git 用户自配)。**留 Task0**:对象存储工作目录 ↔ agent 沙箱本地盘的挂载/同步形态(沙箱跑在本地盘,需与 OSS 双向同步或挂载)。
- ~~**BFF↔omnigent 鉴权形态**~~ **已定**:**header-auth**(前门),数据集受控走"每会话令牌化 MCP 端点 + can()"(见"数据集受控链路")。Task0 仅核验 http MCP transport / 令牌还原 / 有无 header 转发旁路。
- ~~**omnigent 版本钉定 / 部署形态**~~ **已定**:预构建镜像、不 fork、钉 release tag(见组件清单)。
- **MCP 工具确切集合 + 与现有 DJ 管线复用边界**(agent 跑 DJ 是调我们现有 data-pipeline 服务,还是沙箱内直跑 `.dj-venv`?)。
- **模型接入 + 成本治理**:用哪个模型 + omnigent policy 成本上限策略。
- **令牌细节**:TTL / 撤销 / 仅内网可达(Task0 后定具体值)。

## 依赖引用(既有家)
- 外部:omnigent `omnigent-ai/omnigent`(Apache-2.0,v0.2.0 alpha)——spike RESULTS 已实测 openapi/embed/OIDC/policy/sandbox。
- 内部:我们 `can()`(libs/authz)、catalog-driven 注册(ADR-023)、DJ 管线(`pipelines/data_prep/`)、BFF/KC(ADR-025)、owner 模型(ADR-024)。
- 决策:**[ADR-026](../../../adr/ADR-026-dev-workspace-omnigent.md)**(本特性)+ 升级 ADR-019 的 Plan 9 定义;沿用 ADR-011(Cerbos 路线,正交)。

## 给 spec 的 DoR 提示(owner 写 spec 时逐项过)
范围/出口 ✓(出口④ 升级)· 外部依赖事实 ✓(spike RESULTS;Task0 实跑确认)· 数据模型(工作目录/会话/MCP 工具契约 待定)· 行为边界(沙箱越界/危险命令 ASK/无企业用户)· NFR(隔离三道/secret 模型 key/沙箱资源/dev-prod parity)· 验收(图形 runbook + 隔离负例)· 决策留痕(ADR-026)。
