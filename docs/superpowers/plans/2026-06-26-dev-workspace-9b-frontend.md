# Dev Workspace 9b — 前端工作台 + BFF 反代 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development 或 executing-plans。Steps 用 `- [ ]`。
> **前置**:地基(`2026-06-26-dev-workspace.md`,Task 0–6)已合并(BFF 工作区会话装配 `create_workspace_session`、MCP server、令牌就绪)。视觉照高保真原型 `docs/superpowers/prototypes/2026-06-26-dev-workspace-hifi.html`。

**Goal:** 自建 React19「Dev Workspace」页(左树:工作目录/数据目录/Git + 右侧:agent 对话/文件/终端,可拖拽+可收起),经我们 BFF 反代驱动 omnigent;实现 spec US1(工作台会话)+ US2(数据探查)的图形闭环。

**Architecture:** 前端(React19,不持 token)→ 我们 BFF(反代 REST + WS 到 omnigent,注入 header-auth 身份、剥伪造头、CSRF)→ omnigent。会话建立走地基 `create_workspace_session`(铸令牌 + 注册我们的 MCP);对话流经 omnigent `/v1/sessions/{id}/stream`。

**Tech Stack:** React 19 + Vite + react-router-dom 7 + Tailwind(现有控制台,brand #6366F1 / Fira)、monaco(文件)、xterm(终端);BFF FastAPI(`services/gateway/bff`)反代 + WS;vitest;contracts(omnigent openapi 作既有契约,不重生成)。

**门禁:** `make test`(BFF)、`make fe-lint` / `make fe-test` / `make fe-build`(前端)。

---

## 状态(实时)
> **probe-independent 部分完成 ✅(Task 1/3/4)· 后端 278 passed + 前端 39 passed + build OK · 分支 `dev-workspace-9b`**
> **待交互探针 + 后续**:Task 0(omnigent turn 端点 + stream 事件 schema)→ 解锁 Task 2(WS 反代全量)/ Task 5(对话流)/ Task 6(文件·终端)/ Task 7(图形 runbook)。**未硬编码任何未验证的 omnigent 事件契约。**

| Task | 状态 | 产物 |
|---|---|---|
| 0 探针(turn/stream schema) | ✅ 源码级解(RESULTS 9b) | —— |
| 1 BFF 反代身份头 | ✅ | `bff/omnigent_proxy.py`(注入身份+剥伪造头/cookie) |
| 2 SSE 透传反代 | ✅ | `bff/workspace_routes.py`(/stream 透传 + /turn + /resolve) |
| 3 BFF 工作区会话路由 | ✅ | `bff/workspace_routes.py`(身份取自会话) |
| 4 前端外壳 + 左树 | ✅ | `pages/DevWorkspace.tsx`、`devws/LeftTree.tsx`、`api/devws.ts`、路由/导航 |
| 5 对话流 | ✅ | `devws/useSessionStream.ts`+`AgentChat.tsx`+DevWorkspace 接入 |
| 6 文件/终端 | ✅ | `devws/FileViewer.tsx`(monaco)+`Terminal.tsx`(xterm)+`RightPane.tsx` |
| * 左树真数据 | ✅ | DevWorkspace 接 catalog listDatasets(工作目录/git best-effort)|
| 7 图形 runbook | ✅ | `2026-06-26-dev-workspace/RUNBOOK.md`(E 段) |
| live 端到端 | ⏳ 待起 omnigent | RUNBOOK-9b |

---

## File Structure
- `services/gateway/bff/omnigent_proxy.py` — **新增**:REST + WS 反代(注入身份头、剥伪造头、转发 `/v1/ws/*` → omnigent)。
- `services/gateway/bff/workspace_routes.py` — **新增**:HTTP 路由 `POST /v1/ws/sessions`(调地基 `create_workspace_session`)+ `DELETE`(close)。
- `frontend/src/pages/DevWorkspace.tsx` — **新增**:页面外壳(三栏 + 拖拽 + 收起,照原型)。
- `frontend/src/pages/devws/{LeftTree,AgentChat,FileViewer,Terminal}.tsx` — **新增**:四子组件。
- `frontend/src/api/devws.ts` — **新增**:BFF 客户端(建会话、发 turn、订阅 stream、读 catalog/工作目录)。
- `frontend/src/pages/devws/useSessionStream.ts` — **新增**:消费 omnigent stream 事件的 hook。
- `frontend/src/app/Shell.tsx` / 路由 — **改**:加 Dev Workspace 导航项 + 路由。
- 测试:`tests/gateway/bff/test_omnigent_proxy.py`、`frontend/src/pages/devws/*.test.tsx`。

---

## Task 0:探针 — 发送 turn 端点 + stream 事件 schema(外部依赖事实,承重)

> 地基 Task0 验了 MCP/令牌;**前端承重墙 = omnigent 的"发用户消息/turn"端点 + `/v1/sessions/{id}/stream` 事件结构 + 终端 WS**(地基用 `omnigent run` CLI,未碰这些 server API)。**非 TDD,带决策规则。**

- [ ] **Step 1**:起地基 omnigent + host + 一个会话(`create_workspace_session`)。
- [ ] **Step 2**:发现"发送用户消息"端点(openapi 无显式 message/turn 名)——试 `POST /v1/sessions/{id}/...`(候选:`/messages`、`/agent/input`、`/respond`、`/turns`);用 `curl -H X-Forwarded-Email` 实测哪个触发一次 agent turn。记真实端点 + body 到 RESULTS(9b 节)。
- [ ] **Step 3**:连 `GET /v1/sessions/{id}/stream`(WS 或 SSE?实测),记**事件类型 schema**(消息增量、工具调用/结果、turn 结束、错误)——前端渲染对话/工具卡/文件变化全靠它。
- [ ] **Step 4**:记终端 WS(若有)端点 + 帧格式(xterm 对接)。
- [ ] **Step 5**:**决策规则**:① stream 为 WS → BFF 做 WS 反代(Task 2);② 为 SSE → BFF 做 SSE 透传。事件 schema 落 `frontend/src/api/devws.ts` 的类型。Commit RESULTS。

## Task 1:BFF REST 反代(注入身份 + 剥伪造头)

**Files:** Create `services/gateway/bff/omnigent_proxy.py`;Test `tests/gateway/bff/test_omnigent_proxy.py`

- [ ] **Step 1:写失败测试**(给定已认证 BFF 会话 ctx,代理转发到 omnigent 时:注入 `X-Forwarded-Email`=ctx 身份、剥离客户端传入的同名头、透传路径/方法/body)
```python
# tests/gateway/bff/test_omnigent_proxy.py
import httpx
from services.gateway.bff.omnigent_proxy import build_forward_headers

def test_inject_identity_and_strip_forged():
    incoming = {"X-Forwarded-Email": "evil@x", "Content-Type": "application/json", "Cookie": "s=1"}
    out = build_forward_headers(incoming, identity_email="alice@acme.test")
    assert out["X-Forwarded-Email"] == "alice@acme.test"   # 我们注入,非客户端
    assert "Cookie" not in out                              # 不外泄会话 cookie 给 omnigent
    assert out["Content-Type"] == "application/json"
```
- [ ] **Step 2:跑(红)。**
- [ ] **Step 3:实现** `build_forward_headers`(白名单转发头 + 注入身份 + 去 Cookie/伪造头),`async def proxy_rest(request, omni_base, identity_email)` 用 httpx 转发。
- [ ] **Step 4:跑(绿)。** **Step 5:Commit。**

## Task 2:BFF WS/SSE 反代(stream)

> 形态按 Task0(WS 或 SSE)。下方按 WS;若 SSE 则改 StreamingResponse 透传。

**Files:** Modify `services/gateway/bff/omnigent_proxy.py`;Test 续
- [ ] **Step 1:写失败测试**:WS 反代握手时注入身份头、拒未认证、双向转发帧(用 fake 双端测转发逻辑;可测的纯函数 = 帧透传 + 鉴权门)。
- [ ] **Step 2:跑(红)→ Step 3:实现** WS 代理(FastAPI WebSocket ↔ httpx-ws/websockets 到 omnigent;连接前校验 BFF 会话 + CSRF,注入身份头)。**Step 4:绿。Step 5:Commit。**

## Task 3:BFF 工作区会话路由(接地基装配)

**Files:** Create `services/gateway/bff/workspace_routes.py`;Test 续
- [ ] **Step 1:写失败测试**:`POST /v1/ws/sessions`(认证用户)→ 调 `create_workspace_session`(身份取自 BFF 会话,非请求体)→ 返回 `{session_id}`;未认证 401;CSRF 缺失拒。
- [ ] **Step 2:红 → Step 3:实现**路由工厂(复用地基 `create_workspace_session`、`OmnigentClient`、`WorkspaceTokenStore`;agent_id 取 env 默认 `liteai_devws`;mcp_base_url 取 env)。挂到 BFF app。**Step 4:绿。Step 5:Commit。**

## Task 4:前端页面外壳 + 左树

**Files:** Create `frontend/src/pages/DevWorkspace.tsx`、`devws/LeftTree.tsx`、`api/devws.ts`;改路由 + Shell 导航。Test `devws/LeftTree.test.tsx`
- [ ] **Step 1:写失败测试**(vitest):渲染 LeftTree,给定 catalog 数据集 + 工作目录文件 + git 状态 → 三段(工作目录/数据目录/Git)可见、可折叠;点数据集触发 onSelect。
- [ ] **Step 2:红 → Step 3:实现** 外壳(三栏 + 拖拽分隔 + 右栏可收起,**移植高保真原型的结构与 class**)+ LeftTree(数据目录用现有 catalog API;工作目录/Git 用 `api/devws.ts` 经 BFF 反代取)。**Step 4:`make fe-test` 绿 + `make fe-build`。Step 5:Commit。**

## Task 5:Agent 对话(消费 stream + 发 turn)

**Files:** Create `devws/AgentChat.tsx`、`devws/useSessionStream.ts`;Test `AgentChat.test.tsx`
- [ ] **Step 1:写失败测试**:给定 mock stream 事件(用户消息/agent 增量/工具卡/turn 结束),AgentChat 渲染对应气泡 + 工具卡(带 `can() 通过`/`policy:ASK`);composer 发送调 `sendTurn`。
- [ ] **Step 2:红 → Step 3:实现** `useSessionStream`(按 Task0 schema 解析 WS/SSE 事件)+ AgentChat(气泡/工具卡/ASK 审批卡,照原型);发送走 Task0 实测的 turn 端点(经 BFF 反代)。**Step 4:绿 + build。Step 5:Commit。**

## Task 6:文件查看 + 终端

**Files:** Create `devws/FileViewer.tsx`(monaco)、`devws/Terminal.tsx`(xterm);Test 浅(渲染 + tab 切换)
- [ ] **Step 1:写失败测试**:右栏三 tab(文件/终端/数据预览)切换;FileViewer 给定内容渲染只读 monaco;Terminal 挂载 xterm。
- [ ] **Step 2:红 → Step 3:实现**(文件经 BFF 反代读 environment filesystem;终端经 Task0 的终端 WS;数据预览复用 catalog 详情)。**Step 4:绿 + build。Step 5:Commit。**

## Task 7:图形化验收 runbook
- [ ] 写 `docs/superpowers/plans/2026-06-26-dev-workspace/RUNBOOK-9b.md`:登录 → 进 Dev Workspace → 选 coco → 对话"探查 coco" → 见工具卡 `liteai__catalog_read_schema` + 结果 + 文件/终端;拖拽分隔 + 收起右栏;无企业账户进入得友好提示(复用地基 Shell guard)。负例:跨企业数据集不可见/被拒。

---

## 推迟(v-next)
- 多人协作会话 UX(omnigent session perms);富数据预览(Lance 列式);移动端;离线缓存。

## Self-Review
- 覆盖 US1(工作台会话:Task 3 路由 + Task 4/5 UI)+ US2(探查图形闭环:Task 5 工具卡 + Task 6 预览)✓。承重墙(omnigent turn/stream schema)= Task0 探针先验(决策规则),不猜。安全:BFF 注入身份 + 剥伪造头 + 不外泄 cookie(Task1/2),前端不持 token。视觉照已定高保真原型。无 TBD;外部 schema 不确定项全压在 Task0 探针 + 决策规则。
