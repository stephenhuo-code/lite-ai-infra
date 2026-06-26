# Design — Dev Workspace(Plan 9):agent 数据开发台

> HOW。需求(WHAT/WHY)见 **spec.md(owner 待写)**。地基/外部依赖决策落 **[ADR-026](../../../adr/ADR-026-dev-workspace-omnigent.md)**。外部依赖事实见 **[omnigent spike RESULTS](../../spikes/2026-06-26-omnigent-feasibility.md)**(源码级实测)。
> 关哪个出口:S1 出口④ 的降级项 Plan 9 —— 从"code-server + Remote-SSH 半天版"**升级为 agent 工作台**(owner 2026-06-26 重定义)。

## 一句话
基于数据目录的数据集做**数据探查 + 数据管线开发(Data-Juicer + Python)**的 **agent 工作台**:我们自建 React 前端(左树 + agent 对话/文件/终端),后端用 **omnigent**(Apache-2.0 self-host)作 agent runtime + 沙箱,数据能力经**我们的 MCP 工具**喂给 agent(can() 按企业/owner 把关)。

## 架构
```
我们的 React19 控制台 ── 新增「Dev Workspace」页(自建 UI,经 API 驱动 omnigent)
  左树:工作目录(omnigent filesystem API)+ catalog(我们的 API)+ git 树
  右侧:agent 对话 + 文件查看(monaco)+ 终端(xterm)
        │  REST + WS(前端不持 token,沿用现模型)
        ↓
  我们的 BFF ── 反代 /v1/ws/* → omnigent server(REST + WS),注入身份 + CSRF
        │
        ↓
  omnigent ②-⑥(自托管 docker):Server(FastAPI)/Host/Runner(每会话一进程 + bwrap 沙箱)/Harness(claude-sdk)
        │  每会话注册 ↓(POST /v1/sessions/{id}/agent/mcp-servers)
  我们的 MCP server:工具 = 读 catalog 数据集 / 取 OSS 数据 / 跑 DJ recipe / 跑 python / 工作目录+git
        └─ 工具内部走 can() 按企业/owner 把关(数据授权红线)
```
**复用 vs 自建**:omnigent 给 agent runtime/沙箱/harness/policy(难造,直接用);我们自建 = 前端 UI + BFF 反代 + **我们的 MCP 工具**(把"数据探查/管线开发"暴露给 agent)。client 自建(非 iframe/非 React-island 嵌入)—— 因 React19/RR7 与 omnigent embed 期望 React18/RR6 鸿沟(见 spike RESULTS ①)。

## 授权三分层 + 红线(ADR-026 核心)
| 关注 | 谁管 |
|---|---|
| **认证(你是谁)** | **Keycloak**(omnigent OIDC→KC,单一身份)|
| **租户/数据授权(能否碰这份企业数据)** | **我们 `can()`(→S2 Cerbos),在 MCP 工具内 —— 绝不外包 omnigent**(宪法 §2.4 单一出入口 / §1.6 企业硬隔离)|
| **agent 行为治理(shell/tool/cost/working_dir/危险操作 ASK)** | **omnigent PolicyEngine**(自带,我们没有,直接用)|
| **会话协作(谁能 view/edit/run 某会话)** | **omnigent session permissions**(限我们租户内)|

**红线**:租户/数据隔离不外包给 omnigent policy —— omnigent 的 policy 作用对象是 agent 动作,不懂我们的企业/owner/catalog 模型。
**Cerbos(S2)与 omnigent policy 正交、不一起实现**:MCP 工具是接缝,S2 落地把工具内 `can()` 换 Cerbos 即可,不碰 omnigent。

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
- omnigent:`deploy/dev/` 加 omnigent docker compose(+ OIDC→KC 配置)。
- 模型:harness 用 claude-sdk(订阅/API key,env 注入,§5.2)。

## 范围 / 序(epic)
- **Task 0 探针(docker 实跑,探查优先)**:本地起 omnigent(`deploy/docker` bootstrap + compose)→ ① OIDC 接 KC 登录通 ② 注册一个我们的 MCP 工具被 agent 调用 ③ 沙箱 + working_dir 限到工作目录 ④ BFF 能反代 REST+WS。**带退化规则**(若某项不成,记录 + 调整集成形态)。
- 后续 Task:BFF 反代 / 我们的 MCP 工具(catalog→DJ→python→git,逐个 TDD)/ 前端(左树 + chat + terminal + file viewer)/ 隔离负例测试 / 图形 runbook。

## 留待 spec / Task0 钉死(诚实标注,非缺口)
- **工作目录存储形态**:OSS-backed `<企业>/{user}/workspace/` vs omnigent host 沙箱本地盘(持久化/隔离权衡)。
- **MCP 工具确切集合 + 与现有 DJ 管线复用边界**(agent 跑 DJ 是调我们现有 data-pipeline 服务,还是沙箱内直跑 `.dj-venv`?)。
- **BFF↔omnigent 鉴权具体形态**:omnigent-OIDC(指 KC)vs BFF header-auth 代理 —— Task0 实测定。
- **模型接入 + 成本治理**:用哪个模型 + omnigent policy 成本上限策略。
- **omnigent 版本钉定 / 升级策略**(alpha,API 可能变)。

## 依赖引用(既有家)
- 外部:omnigent `omnigent-ai/omnigent`(Apache-2.0,v0.2.0 alpha)——spike RESULTS 已实测 openapi/embed/OIDC/policy/sandbox。
- 内部:我们 `can()`(libs/authz)、catalog-driven 注册(ADR-023)、DJ 管线(`pipelines/data_prep/`)、BFF/KC(ADR-025)、owner 模型(ADR-024)。
- 决策:**[ADR-026](../../../adr/ADR-026-dev-workspace-omnigent.md)**(本特性)+ 升级 ADR-019 的 Plan 9 定义;沿用 ADR-011(Cerbos 路线,正交)。

## 给 spec 的 DoR 提示(owner 写 spec 时逐项过)
范围/出口 ✓(出口④ 升级)· 外部依赖事实 ✓(spike RESULTS;Task0 实跑确认)· 数据模型(工作目录/会话/MCP 工具契约 待定)· 行为边界(沙箱越界/危险命令 ASK/无企业用户)· NFR(隔离三道/secret 模型 key/沙箱资源/dev-prod parity)· 验收(图形 runbook + 隔离负例)· 决策留痕(ADR-026)。
