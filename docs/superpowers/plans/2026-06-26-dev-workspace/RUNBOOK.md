# RUNBOOK — Dev Workspace 地基(受控数据链路)验收

> Dev Workspace 全部验收(一份)。分层:**A 门禁(自动,主验收)** + **B 受控链路 live** + **C 9c 工具/管线 live** + **D 9d 持久化 live** + **E 前端图形 live**(B–E 需 `make ws-up` 起栈 + host + 订阅 token)。

## A. 门禁(自动)—— 受控链路逻辑的主验收
对应 SC-002(隔离负例 100% 拦)、SC-004(零沙箱逃逸,沙箱部分见 B/Task3-4)。
- [ ] `make test` 全绿(含 `tests/dev_workspace/` 15 用例:令牌铸/验/撤销、令牌→Context、catalog 工具 can() 放行/拒绝、BFF 会话装配 + 剥伪造头、隔离负例)。
- [ ] `make lint` 全绿(import 分层 KEPT)。
- **可证伪点**:`tests/dev_workspace/test_isolation.py` —— 跨企业读私有数据集**被拒且不泄露元数据**;伪造令牌 → 无 Context(unauthenticated);撤销会话令牌 → 拒。任一变绿失败即受控链路破。

## B. live 集成(可选,需 docker + Claude 订阅 token)
> 镜像 Task0,但注册的是**我们真实的 MCP server(含 catalog_read_schema)**,验"agent 经令牌化工具读真实数据集 schema,每次过 can()"。

### 前置(一条命令)
- [ ] **一次性**:`claude setup-token` → 存 `secrets/omnigent.token`;有一个本企业数据集(`coco`,没有先 `make bootstrap-catalog` + 控制台上传)。
- [ ] **`make ws-up`** —— 起全栈(全后台):omnigent 自构建镜像(缺则自动 build)+ omnigent 容器 + deps + 全部服务(**含 MCP server**)+ **host/runner** + **前端**。打开 `http://localhost:5173/workspace`。停:`make ws-down`;日志在 `.dev/`。
> dev 也可免 host 用 `omnigent run` 直挂 spec 验工具(见下"快验")。

### 步骤(受控链路 e2e)
1. [ ] **建工作区会话**:用 `create_workspace_session`(`services/gateway/bff/workspace.py`)铸令牌 + 注册我们的 MCP(`http://localhost:8910/s/<token>/mcp`)到 omnigent 会话。
   - 期望:返回 `session_id`;我们 MCP server 日志出现带 `<token>` 的连接(initialize + list_tools)。
2. [ ] **探查(正路)**:触发 agent "读 coco 的 schema"。
   - 期望:`liteai__catalog_read_schema` 返回 `format=webdataset / num_samples / owner=你`;MCP server 侧 `can(dataset.read, coco)=allow(ent-demo, owner=你)`。
3. [ ] **负例·跨企业**:用另一企业身份的令牌读 `coco` → 工具返回 `{"error":"forbidden"}`,**无元数据泄露**。
4. [ ] **负例·伪造令牌**:`curl` 我们的 MCP server 用不存在的 token 调 `whoami` → `{"error":"unauthenticated"}`。
5. [ ] **负例·沙箱越界(Task3/4 集成时补)**:agent 设 `os_env.sandbox` 限 `write_paths` 到 workspace,尝试写 `/etc/x` → 被拒。**本计划记为待 9c/Task 集成**(Task0 已源码确认沙箱;live 越界测随沙箱工具落地)。

### 快验(免 host,镜像 Task0)
直接用 `omnigent run` 挂一个 spec(`executor.harness: claude-native` + `tools.liteai: {type: mcp, transport: http, url: http://localhost:8910/s/<手铸token>/mcp}`),prompt "call liteai__catalog_read_schema for dataset coco"。看工具返回 + MCP 日志 `can()=allow`。(Task0 已用此法证承重墙②。)

## C. 9c 数据工具集 + 管线(live,可选)
> 在 B 起好的栈上,验 agent 经新工具走"探查→管线→注册回 catalog"。
- [ ] agent 调 `liteai__catalog_sample` 对 coco 采样 → 返回定位/格式(can()=allow)。
- [ ] agent 调 `liteai__dj_scaffold` 生成 recipe 到工作目录 → 沙箱跑 `dj-process` → 产出 `output/coco-clean.lance`。
- [ ] agent 调 `liteai__register_dataset`(location 落本人 `processed/` 前缀)→ 数据目录出现 `coco-clean`(owner=你)。
- [ ] **负例**:`liteai__oss_read path=ent-other/...`(跨企业)→ `forbidden`、不触达存储;`register_dataset` location 落他人前缀 → `forbidden`。

## D. 9d 工作目录持久化 + 本地 git(live,可选)
> 在 B 起好的栈上,验"工作目录跨会话持久化(OSS 按 workspace 隔离)+ 本地 git",对应 spec US5。
> 涉及组件:`bff/workspace_store.py`(prefix/hydrate/persist)、`bff/omnigent_fs.py`(真实 syncer)、`dev_workspace_mcp/tools/git.py`。
- [ ] **持久化往返**:
  1. 建工作区会话(带 ws 名,如 `coco-clean`)→ BFF 从 OSS `<企业>/{owner}/workspace/coco-clean/` **水合**到 omnigent environment 工作目录。
  2. 让 agent 在工作目录写文件(如 `recipe.py`)。
  3. **关会话** → BFF **持久化**(遍历 environment `/changes` → 写回 OSS,`omnigent_fs.listrel/read` + OSS `put_object`)。
  4. **重开同一 ws** → 水合 → `recipe.py` **仍在**(证跨会话持久化)。
- [ ] **本地 git**:agent 调 `liteai__git_status`(左树 Git 段显示改动)→ `liteai__git_commit`(本地提交)→ `liteai__git_log` 见该提交。**确认无 push**(远端 git 用户自配)。
- [ ] **负例·越界写**:agent 试图写工作目录外(如 `/etc/x`)→ 被沙箱拒(`write_paths` 限本 workspace)。
- [ ] **负例·跨 owner**:用另一 owner 令牌读他人 `workspace/` 前缀 → `oss_read` 返 `forbidden`(workspace_store prefix 守卫)。

## E. 前端图形 live(US1 + US2,照高保真原型)
> 前置同 B(`make ws-up` 起全栈,含 host + 前端)。视觉照 `../../prototypes/2026-06-26-dev-workspace-hifi.html`。
- [ ] 浏览器登录(KC)→ 左侧导航点 **「Dev Workspace」**(`/workspace`)。
- [ ] **左树**三段:工作目录 / 数据目录(展开见**真实数据集** `coco`)/ Git;段头可折叠。
- [ ] 对话 **"探查一下 coco 数据集"** → 用户气泡即时 + agent **流式回复** + **工具卡 `liteai__catalog_read_schema`**(「can() 通过」)→ webdataset/样本数/owner=你;右上受控 chip(沙箱/policy/企业·owner)。
- [ ] **"写个 DJ recipe 过滤短文本并跑一下"** → agent 写 `recipe.py` → **ASK 审批卡**(policy:ASK)→ 点「批准」;右栏「文件」tab 看 `recipe.py`(**monaco**)、「终端」tab 看 `dj-process` 输出(**xterm**,含 `can()=allow`)。
- [ ] **"把结果注册回数据目录"** → 左树数据目录出现 `coco-clean`(owner=你,processed)。
- [ ] **交互**:拖拽分隔(对话 ≥380/右栏 ≥340)· 右栏收起/展开 · tab 切换 · 点数据集→预览;前端**不持 token**(devtools 查无 access token)。
- [ ] **隔离负例**:无企业账户进入 → 友好「待分配」提示(FR-011);左树只列本企业数据集、跨企业读被拒不泄露;危险/高成本 → ASK 拦截(FR-010)。
- **判据(SC)**:打开→一次探查结果 ≤5 步/数分钟(SC-001);工具卡+流式+文件/终端可见 = US2 图形闭环;隔离负例全拦。

## 失败处理
任一步失败走 `superpowers:systematic-debugging`;不假绿、不跳步。沙箱/host 认证类与外部依赖相关的偏差回写 Task0 RESULTS + design。
