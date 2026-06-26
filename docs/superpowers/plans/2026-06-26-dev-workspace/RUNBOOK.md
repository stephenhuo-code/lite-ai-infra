# RUNBOOK — Dev Workspace 地基(受控数据链路)验收

> 受控链路 + 数据工具 + 持久化的验收。**前端图形端到端验收见同目录 [RUNBOOK-9b.md](./RUNBOOK-9b.md)。**
> 分层:**A 门禁(自动,主验收)** + **B 受控链路 live** + **C 9c 工具/管线 live** + **D 9d 持久化 live**(B/C/D 需起 omnigent + host + 订阅 token)。

## A. 门禁(自动)—— 受控链路逻辑的主验收
对应 SC-002(隔离负例 100% 拦)、SC-004(零沙箱逃逸,沙箱部分见 B/Task3-4)。
- [ ] `make test` 全绿(含 `tests/dev_workspace/` 15 用例:令牌铸/验/撤销、令牌→Context、catalog 工具 can() 放行/拒绝、BFF 会话装配 + 剥伪造头、隔离负例)。
- [ ] `make lint` 全绿(import 分层 KEPT)。
- **可证伪点**:`tests/dev_workspace/test_isolation.py` —— 跨企业读私有数据集**被拒且不泄露元数据**;伪造令牌 → 无 Context(unauthenticated);撤销会话令牌 → 拒。任一变绿失败即受控链路破。

## B. live 集成(可选,需 docker + Claude 订阅 token)
> 镜像 Task0,但注册的是**我们真实的 MCP server(含 catalog_read_schema)**,验"agent 经令牌化工具读真实数据集 schema,每次过 can()"。

### 前置
- [ ] `make deps-dev`(KC/MinIO/PG)+ `make bootstrap-catalog`(建桶 + metalake `ent_demo`)。
- [ ] 有一个本企业数据集(如 `coco`,owner=你);没有则先经控制台上传+注册。
- [ ] **本地自构建 omnigent 镜像(首次/ref 或补丁变更后)**:`scripts/omnigent_build.sh dev`(从 `third_party/omnigent` 钉定 ref + patch-queue build 出 `omnigent-server:dev`/`omnigent-host:dev`;ADR-026 §1)。**未 vendor 过先** `git submodule update --init third_party/omnigent`。
- [ ] 起 omnigent:`docker compose -f deploy/dev/omnigent.yml up -d`(用本地自构建镜像;header 模式;绑 127.0.0.1:8900)。
- [ ] 起我们的 MCP server:`GRAVITINO_URL=http://localhost:8091 uv run uvicorn services.dev_workspace_mcp.app:asgi --host 127.0.0.1 --port 8910`。
- [ ] 模型凭证:`claude setup-token` → 存 `CLAUDE_CODE_OAUTH_TOKEN`(你的订阅;不入库,§5.2)。
- [ ] 起一个 host/runner(Task0 实证 server 单独不能执行):`CLAUDE_CODE_OAUTH_TOKEN=… uv run --project <omnigent 源> omnigent host http://localhost:8900`(header 模式 host 认证细节见 Task0 RESULTS;dev 也可用 `omnigent run` 直挂 spec 验工具,见下"快验")。

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

## 失败处理
任一步失败走 `superpowers:systematic-debugging`;不假绿、不跳步。沙箱/host 认证类与外部依赖相关的偏差回写 Task0 RESULTS + design。
