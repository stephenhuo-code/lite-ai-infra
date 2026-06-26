# RUNBOOK-9b — Dev Workspace 前端图形化端到端验收

> 覆盖 spec **US1(工作台会话)+ US2(数据探查)+ US4(管线,经对话)** 的图形闭环。
> 视觉照高保真原型 `../../prototypes/2026-06-26-dev-workspace-hifi.html`。需真起后端栈(同主 RUNBOOK B 前置)。

## 前置(一键起,非逐步手动)
- [ ] **一次性**:`claude setup-token`(浏览器授权)→ 输出存 `secrets/omnigent.token`(gitignore;你的订阅,§5.2 不入库)。
- [ ] **一次性**:有一个本企业数据集(如 `coco`,owner=你;没有则先经控制台上传+注册;`make bootstrap-catalog` 建桶/metalake)。
- [ ] **起全栈一条命令**:`make ws-up`
  - = omnigent 自构建镜像(缺则自动 build,ADR-026 §1)+ omnigent 容器 + `make up`(deps:KC/MinIO/PG/Gravitino + 全部服务**含我们的 MCP server**,经 `dev_services.sh` 服务表自动起)。
- [ ] **另开两个终端跑前台进程**:
  - `make omnigent-host`(host/runner,读 `secrets/omnigent.token`)
  - `cd frontend && npm run dev` → 浏览器开 `/workspace`
- [ ] 停:`make ws-down`。
> 说明:除两个前台进程(host、前端)+ 一次性 token/数据集,其余全由 `make ws-up` 编排——复用现有 `make up` + `dev_services.sh` 服务表,无单独编排脚本。

## 图形步骤(US1 + US2)
1. [ ] 浏览器登录控制台(KC)→ 左侧导航点 **「Dev Workspace」**(`/workspace`)。
2. [ ] **左树**:见三段——**工作目录**、**数据目录**(展开见**真实数据集** `coco`,来自 catalog)、**Git**。点段头可折叠。
3. [ ] 中间对话框输入 **"探查一下 coco 数据集"** → 回车/发送。
   - 期望:右上**受控 chip**(沙箱 / policy / 企业·owner);**用户气泡**(靛蓝右对齐)即时出现;**agent 流式回复**(文本逐字)+ **工具卡 `liteai__catalog_read_schema`**(带「can() 通过」)→ 返回 webdataset / 样本数 / owner=你。
4. [ ] 输入 **"写个 Data-Juicer recipe 过滤短文本并跑一下"**。
   - 期望:agent 写 `recipe.py`;触发 **ASK 审批卡**(policy:ASK,显示 run_dj)→ 点 **「批准」**。
   - **右栏**:切「文件」tab 看 `recipe.py`(**monaco** 高亮);切「终端」tab 看 `dj-process` 输出(**xterm**,含 `can()=allow`)。
5. [ ] 输入 **"把结果注册回数据目录"** → 左树**数据目录**出现 **`coco-clean`**(owner=你,processed)。

## 交互验收(原型一致)
- [ ] **拖拽**对话↔右栏分隔条 → 比例随手调(对话区 ≥380px、右栏 ≥340px)。
- [ ] 右栏「收起」按钮 → 变窄竖条;点竖条 **展开**回原宽。
- [ ] 右栏 tab 切换:文件 / 终端 / 数据预览;点左树数据集 → 预览 tab 显示该数据集。
- [ ] 前端**不持 token**(开发者工具查无 access token;仅 BFF 会话 cookie + csrf)。

## 隔离负例(图形)
- [ ] **无企业账户**登录进 Dev Workspace → 得**友好「待分配」提示**(复用 Shell guard FR-011),不悬空、不报原始 403。
- [ ] 左树数据目录**只列本企业数据集**;对话让 agent 读另一企业数据集 → 被拒、无元数据泄露(can() / 跨企业)。
- [ ] agent 危险/高成本操作 → **ASK 审批卡**拦截,未批准不执行(FR-010)。

## 验收判据(对应 SC)
- SC-001:从打开工作台到看到一次探查结果,**5 步对话内 / 数分钟内**。
- US2:工具卡 + 流式回复 + 文件/终端可见 = 数据探查图形闭环成立。
- 隔离负例全部被拦(无企业提示 / 跨企业不可见 / ASK 拦截)。

## 失败处理
任一步失败走 `superpowers:systematic-debugging`;不假绿。omnigent SSE 事件 discriminator 若与 `useSessionStream` 的 mapping 不符(探针 RESULTS 9b 取自官方客户端,理论一致)→ 改 `useSessionStream.ts` 的 mapping 一处,并回写 RESULTS。
