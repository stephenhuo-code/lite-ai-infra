# Spike RESULTS — omnigent 作 Dev Workspace agent 后端是否可用(3 承重墙)

> 状态:**调研/事实采集**(源码 spike,clone `omnigent-ai/omnigent` @ /tmp 读真码 + openapi)。日期 2026-06-26。
> omnigent v0.2.0 **alpha**,Apache-2.0,Python 3.12 后端 + React/Vite/xterm 前端(`ap-web`)。**非 Databricks 官方**(omnigent-ai 组织;支持 Databricks 作模型供应商)。
> 决策背景:Plan 9 Dev Workspace 从"code-server 半天版"升级为 agent 工作台;owner 设想 = **复用我们 client + omnigent 作 ②-⑥ agent 后端**。

## 架构(owner 6 层图 + 源码核对)
`Client① ⇄ Server②(FastAPI) ⇄ Host③ ⇄ Runner④(每会话一进程,沙箱)⇄ Harness⑤(claude-sdk/codex/...)⇄ 模型⑥`

## 承重墙逐条(源码证据)

### ① client↔server 协议 + client 复用 —— ✅ 有契约 + 有嵌入入口(但版本鸿沟)
- **`openapi.json` 53 个 REST 端点**(契约化,非逆向)。关键:`/v1/sessions`(增删改查)、`/v1/sessions/{id}/agent/mcp-servers`(**每会话注册 MCP server!**)、`/policies`+`/policies/evaluate`、`/permissions`+`/owner`、`/resources/environments/.../{filesystem,shell,search}`、`/resources/files`。WS:`/sessions/updates`、terminal。
- **`ap-web/src/embed.tsx`**:导出 `OmnigentApp` 纯 React 组件,**专为嵌进 host monolith(原文举例 Databricks)的 React 树**设计,接 host transport(API fetcher + WS URL)+ host 主题/router。
- ⚠️ **版本鸿沟**:embed 把 React/react-router 设为 **externals,期望 host 提供 React 18 / react-router 6.30**;**我们是 React 19 / react-router-dom 7**。RR6↔RR7 API 差异大 → **直接 React-island 嵌入不可行/高风险**。
  - **可行替代**:① **iframe**(omnigent ap-web 独立跑,我们 Dev Workspace 页 iframe 它;版本完全解耦,最省、最稳;UX = 我们外壳 + omnigent 内容)② **自建瘦客户端**对着 openapi.json + WS 写(React 19 原生 UX,但重造 chat/files/terminal,工作量大)。

### ② 鉴权桥(接我们 Keycloak)—— ✅ 原生支持
- `OMNIGENT_AUTH_ENABLED=1` + `OMNIGENT_OIDC_ISSUER=<我们 KC>` → omnigent server 走**完整 OIDC 登录**(指我们 lite-ai realm)。`deploy/README` 明确:有 OIDC_ISSUER 即 OIDC 模式,否则内置 accounts。**需 HTTPS**(session cookie `__Host-` 前缀)。
- 另支持 **header-auth 代理**(deploy/README:202)→ 我们 BFF 可注入身份头,omnigent 信任。
- 结论:omnigent OIDC 直指 KC(用户在我们 KC 登录,omnigent 同源身份);或 BFF header-auth 桥。

### ③ 隔离(企业/owner)—— ✅ 原语齐全,数据隔离靠我们 MCP 工具
- omnigent 自带:**policy 引擎**(`omnigent/policies/`:base/registry/builtins safety,per-session `/policies`+`evaluate`,限 shell/编辑/token/工具/成本)+ **sandbox**(`omnigent/sandbox/{bwrap,seatbelt}` 本地 FS/网络隔离;云沙箱 Modal/E2B/K8s 等)+ session `owner`/`permissions`。→ **代码执行/行为隔离** omnigent 自己管。
- **我们的数据隔离(catalog/OSS/工作目录)落点 = 每会话注册"我们的 MCP server"**(`/v1/sessions/{id}/agent/mcp-servers`):把"读数据集 / 跑 DJ+python / 工作目录+git"做成 MCP 工具,**工具内部走我们的 `can()` 按企业/owner 把关**。agent 只能经我们的工具碰数据 → 隔离在我们这层强制。分工:**omnigent=agent runtime+代码沙箱+行为策略;我们=数据访问工具(can() 边界)**。

## 总判断
**可用,且"复用 client + omnigent ②-⑥"成立。** 三承重墙:②鉴权 ✅(OIDC→KC)③隔离 ✅(MCP 工具 can() + omnigent 沙箱/policy)①协议 ✅ 有 openapi 契约,但 **client 复用方式因 React19/RR7 vs 18/RR6 鸿沟,需选 iframe 或自建瘦客户端(非直接 React-island 嵌入)**。

## 待确认(留 plan Task 0 实跑确认)
- **docker compose up 实跑**:本 spike 为源码级;`deploy/docker` 有 `bootstrap.sh + docker compose up -d`。plan Task 0 = 本地起 omnigent,确认 boot + OIDC 接 KC 登录 + 注册一个我们的 MCP 工具被 agent 调用 + 沙箱限到工作目录。
- alpha 稳定性 / 升级风险;两套后端并存运维。
- 模型接入:harness 用 claude-sdk(API key/订阅);本平台用哪个模型 + 成本治理(policy 成本上限可用)。
