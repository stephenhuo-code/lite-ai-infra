# 验收 Runbook —— Plan 9a:omnigent 集成(Workspace 对话窗)

> **这份文档给谁看**:给 owner(你)照着做验收,**不用读代码、不用懂 curl**。
> 每一步先说**这步在验什么**、**你应该看到什么**;具体命令收在每步末尾的「怎么做(命令)」折叠块里。
> 带「执行者代跑」标记的步骤是后台/看不见的环节,由执行者(AI/工程)跑完、把结果用大白话摆给你确认。
>
> **验收对应的需求**:spec.md 的成功标准 SC-001 ~ SC-005、功能需求 FR-001 ~ FR-008。每步标了对应编号。
>
> **一句话背景**:你用平台账号登录控制台 → 进「Workspace」→ 和一个 AI agent 对话,回复是一点点冒出来的;
> 两个不同账号各聊各的、互相看不到;这套 AI 后端(omnigent)是我们自己编译、自己托管的。

---

## 0. 先把整套环境起起来

**这步在验什么**:一条命令能不能把整套 9a 环境(登录系统 Keycloak + AI 后端 omnigent + 网关 + 前端)按正确顺序起齐。
**你应该看到什么**:命令最后打印「ws-up 完成。栈就绪」,框出**唯一入口 `http://localhost:8090`**。前端已由网关在 8090 **同源发出**,**你不用再单独起任何前端服务、也没有第二个网址要记**。

> 起栈顺序是有讲究的:先起登录系统和 AI 后端,**网关必须知道 AI 后端在哪**(否则对话发不出去);**前端要先 build 好,网关启动时才能把它发出来**。`make ws-up` 已经把顺序和「等它真的起好了再起下一个」都安排好了。
> **只有一个入口:`http://localhost:8090`** —— 控制台、登录、Workspace 全在这。(登录时会被自动带去 Keycloak 填一下密码再弹回 8090,那不是另一个入口。)

<details><summary>怎么做(命令)</summary>

```bash
# 一条命令起齐后端栈(Keycloak + omnigent + 网关),并逐个等就绪:
make ws-up

# 它会自动:① 起 Keycloak/MinIO 并等 Keycloak 就绪
#          ② 把测试用户 alice/bob 补建好、加进企业(幂等,跑几次都行)
#          ③ 自编译 omnigent server+host 镜像并起 omnigent,等 /health
#          ④ build 前端 dist + 起网关(gateway:8090,网关同源发前端 + 注入 OMNIGENT_BASE_URL=127.0.0.1:8900)
#          ⑤ 打印唯一入口 http://localhost:8090

# 前端不用单独起 —— 网关已在 8090 同源把 build 好的前端发出来了,直接开浏览器即可。
# (改了前端代码要重新生效:make fe-build 重 build;真·热更新延后,见计划。)

# 关于 AI 模型凭据:omnigent 需要一个「订阅 token」才能让 agent 调用模型。
# 它放在 secrets/omnigent.token(不进代码仓);ws-up 会自动从这个文件读出来注入,你不用管。
# 万一报「缺订阅 token」,说明这个文件不在 —— 把你的 claude 订阅 token 放到 secrets/omnigent.token 即可。
```

**就绪标志**(ws-up 末尾会打印):
- **唯一入口 `http://localhost:8090`** —— 控制台 + 登录 + Workspace 都在这(网关同源发前端)。脚本还会自检一行「✓ 网关已同源发前端」。
- 后台依赖(不用直接开):Keycloak `:8080`(登录中转)、omnigent `:8900/health`、gateway healthz `:8090/healthz`。
</details>

---

## 1. alice 登录 → 进 Workspace → 发消息 → 回复一点点冒出来

**对应**:SC-001(登录后 ≤3 步开始对话)、SC-002(回复渐进出现)、FR-001/FR-002。

**这步在验什么**:登录的用户能不能进对话窗、发条消息、看到 agent 回复;而且回复是**逐字/逐段冒出来**的,不是干等很久整段蹦出来。

**你该看到什么**:
1. 打开 **`http://localhost:8090`**(唯一入口),**没登录会被弹去 Keycloak 登录页**(用 `alice` / `alice` 登录),填完自动弹回 8090。
2. 登录后进控制台,左侧菜单「工作台」下点 **Workspace**。
3. 第一次进是空的,中间写着「选择或新建一个会话」。点左上角紫色按钮 **+ 新会话**。
4. 下面对话框里输入「你好,简单介绍下你自己」并发送。
5. **关键**:agent 的回复是**一段段、渐进出现**的(先冒出开头,再慢慢补全),不是空白几秒后整段蹦出。这就是 SC-002 通过。

> 如果回复迟迟不来或报错(比如「agent 不可用」),不要当成功 —— 记下来,这说明 AI 后端或模型凭据有问题。

---

## 2. alice 继续聊(记得上文) + 新建会话(各聊各的)

**对应**:FR-003(多会话、各自上下文独立)。

**这步在验什么**:同一个会话里 agent 记不记得刚才说过的话;新建一个会话是不是「干净的」、不带上一个会话的上下文。

**你该看到什么**:
1. 在刚才那个会话里**接着发第二条**,比如「我刚才让你做什么来着?」—— agent 应该能**接上文**回答(说明同一会话上下文连续)。
2. 再点 **+ 新会话**,左侧会多出一条会话;在新会话里发「你还记得我们之前聊了什么吗?」—— agent **不应该**知道上一个会话的内容(说明会话之间是独立的)。
3. 左侧会话列表里现在有**两条会话**,点来点去能切换,各自显示各自的对话历史。

---

## 3. bob 登录(另一个浏览器/无痕窗)→ 看不到 alice 的会话(隔离·重点)

**对应**:SC-003(双用户隔离,**这是最关键的负向验收**)、FR-004。

**这步在验什么**:换一个账号登录,**他只能看到自己的会话,看不到、也打不开别人的会话**。这是多租户平台的底线 —— 没有它绝不能上线。

**你该看到什么**:
1. **另开一个无痕窗口**(或另一个浏览器),打开 **`http://localhost:8090`**,用 `bob` / `bob` 登录。
2. 进 Workspace —— bob 的会话列表是**空的**(他还没建过会话),**绝对不该出现 alice 刚才建的那两条会话**。
3. bob 点 **+ 新会话**、发条消息,聊起来。回到 alice 的窗口刷新一下 —— alice 的列表里**也不该出现 bob 的会话**。
4. **负向重点**:bob 看不到 alice 的会话标识,自然点不开;就算有人手里攥着 alice 的会话 id 想用 bob 的身份去开,也会被挡(后台已验证,见下方第 6 步)。

> 看到「alice 列表里只有 alice 的、bob 列表里只有 bob 的,谁也看不到谁」= SC-003 隔离通过。这一条务必亲眼确认。

---

## 4. 后台:每个活跃用户有各自独立的沙箱容器(外部隔离)〔执行者代跑〕

**对应**:FR-005(每用户/会话一个隔离 managed 沙箱)。

**这步在验什么**:alice 和 bob 的 agent **不是跑在同一个进程里**,而是各自跑在一个**独立的 docker 容器沙箱**里 —— 物理上就隔开了,互不干扰。

**你该看到什么(执行者把结果用大白话告诉你)**:后台 `docker ps` 会看到若干个名字以 `omnigent-managed-` 开头的容器,**一个活跃用户/会话对应一个**。alice 在用就有 alice 的那个,bob 在用就有 bob 的那个,名字各不相同。这就是「各自隔离沙箱」。

<details><summary>怎么做(命令,执行者跑)</summary>

```bash
# 看动态拉起的 managed 沙箱容器(每个活跃用户/会话一个,名字各不同):
docker ps --filter name=omnigent-managed- --format '{{.Names}}\t{{.Status}}'
```
</details>

---

## 5. 改一行 omnigent 代码 → 自己重编译 → 改动生效(我们自维护、自编译)〔执行者代跑〕

**对应**:SC-004 / SC-005、FR-007(我们自己的源、自己编译的镜像,dev/prod 同源,不依赖上游预构建镜像)。

**这步在验什么**:omnigent 是**我们自己 fork 的代码**,改一行就能重编译生效;跑的镜像是**我们自己编译的 `:dev`**,不是从网上拉的别人的成品镜像。

**你该看到什么(执行者把结果摆给你)**:
1. 执行者在我们的 fork 里改一处(比如让 agent 每条回复前都加个固定前缀),重新编译、重启 omnigent。
2. 你在 Workspace 里**再发一条消息**,会看到 agent 的回复**带上了那个新前缀** —— 说明改动真的生效了(SC-004)。
3. 执行者给你看 `docker images` 里 omnigent 的镜像 tag 是 `:dev`、是本地刚编译出来的(SC-005)。

<details><summary>怎么做(命令,执行者跑)</summary>

```bash
# 1) 在 fork 里改一行(示范:给回复加前缀),改的是 third_party/omnigent 里的源码(我们的 fork submodule)
# 2) 重编译 + 重启 omnigent:
scripts/omnigent_build.sh dev      # 自编译 server+host:dev 镜像
docker compose -f deploy/dev/omnigent/docker-compose.yml up -d   # 用新镜像重起

# 3) 回 Workspace 再发一条消息,看回复有没有带上新前缀(改动生效 = SC-004)

# 4) 证明镜像是我们自己编译的 :dev(不是上游预构建):
docker images | grep omnigent
#   omnigent-server   dev   ...   (本地构建,刚刚 CREATED)
#   omnigent-host     dev   ...
```

> 验完记得把那行示范改动撤掉、重新 `omnigent_build.sh dev` + `up -d` 还原。
</details>

---

## 6. 负向:未登录进不去、伪造身份头进不来〔执行者代跑〕

**对应**:FR-001(未认证必跳登录)、SC-003 / FR-004 / FR-008(信任边界:前端不持 token,浏览器伪造身份头到不了 AI 后端)。

**这步在验什么**:
- **A. 未登录访问对话窗** → 直接被弹去登录,**绝不**把页面/数据放出去。
- **B. 有人伪造身份头**(假装是别人)直接打网关 → 被挡在门外,**那个伪造的头永远到不了 AI 后端**。网关是唯一信任边界:它只认「你这次浏览器会话里验证过的身份」,绝不信请求里塞的头。

**你该看到什么(执行者把结果摆给你)**:
- A:无痕窗口直接打开 Workspace 链接,没登录 → 跳到 Keycloak 登录页(看不到任何会话内容)。
- B:执行者直接对网关发一个**没有登录会话、但塞了假身份头** `X-Forwarded-Email: attacker@evil.test` 的请求 → 网关回 **401 未认证**,假身份头被忽略,根本没转发给 omnigent。

<details><summary>怎么做(命令,执行者跑)—— 已实测,结果如下</summary>

```bash
# B1) 没会话访问受保护接口 → 401(网关守门):
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8090/v1/ws/agents
# 实测:401   body: {"reason":"unauthenticated"}

# B2) 没会话 + 伪造身份头 → 仍 401,伪造头无效、到不了 omnigent:
curl -s -o /dev/null -w "%{http_code}\n" \
  -H "X-Forwarded-Email: attacker@evil.test" http://localhost:8090/v1/ws/agents
# 实测:401   body: {"reason":"unauthenticated"}

# B3) 就算直接打 omnigent(只本机回环可达),不带网关注入的身份头也被拒:
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8900/v1/agents
# 实测:401   {"error":{"code":"unauthorized","message":"Authentication required"}}
```

> 更强的保证(单元测试已覆盖):**带一个真实登录会话 + 同时塞伪造头**时,网关把发给 omnigent 的身份**强制改成会话里那个真实身份**(alice),伪造的 attacker@evil 被丢弃。见 `tests/gateway/bff/test_omnigent_proxy.py::test_injects_session_email_and_strips_forged`。
</details>

---

# 「智能体库」验收(Plan 9a · 智能体库 / ADR-027)

> **这一段验什么(大白话)**:平台多了一个「智能体库」页 —— 企业管理员能在里面**自己造一个 AI 角色**(比如"客服助手",给它起名字、写一段它该怎么说话的提示词);
> 同企业的普通成员进对话窗时能**从库里挑这个角色**来聊,聊起来后**这个会话就锁定用它、中途换不了**;
> 别的企业的人**既看不到、也用不了**你造的角色;普通成员**根本没有"新建"按钮**,就算他绕过界面直接调接口,服务端也会**拒绝**。
> 企业默认可见 4 个本企业智能体:minimax、debby、codex、polly；列表不再并列展示"内置"模板卡片。
>
> **你该看到什么**:智能体库里有 minimax、debby、codex、polly 四个"本企业"智能体,不再并列展示"内置"模板卡片。管理员能编辑 debby,能删除 polly;刷新后结果保持。普通成员没有编辑/删除入口。
>
> **对应需求**:SC-001 ~ SC-005、FR-001 ~ FR-008、User Story 1/2/3(见 `../2026-06-30-agent-library/spec.md`)。每步标了编号。
> **前置**:第 0 步那套环境已起好(`make ws-up`,唯一入口 `http://localhost:8090`),`alice`/`alice`(企业管理员)、`bob`/`bob`(普通成员)都在企业 `ent-demo`。

---

## 智-1. alice(企业管理员)建一个"客服助手"

**对应**:SC-001、FR-003、FR-004、User Story 2。

**这步在验什么**:企业管理员能不能在「智能体库」里**自己新建一个智能体**(名字 + 系统提示词),建完**立刻在列表里出现、标着「本企业」**。

**你该看到什么**:
1. 用 `alice` / `alice` 登录 `http://localhost:8090`,左侧菜单进 **「智能体库」**。
2. 因为 alice 是**企业管理员**,页面右上能看到一个 **「新建智能体」** 按钮(普通成员看不到这个,下一步验)。
3. 点「新建智能体」,在弹窗里填:
   - **名字**:`客服助手`
   - **系统提示词**:`你是友好的客服,只用中文简短回答`
   - 模型留空(用模板默认即可);基底固定是 `claude-native`(平台已注入全局共享订阅,唯一能跑的)。
4. 点「创建」。弹窗关掉,**列表里立刻出现「客服助手」这一条,带「本企业」标记**(说明它归 ent-demo、只有本企业可见)。列表中不再并列展示"内置"模板卡片。

> 如果创建报错(比如"重名""无权限""不可用"),那是**明确的中文提示**,不会静默卡住 —— 看到提示按提示处理即可,别当成功。

---

## 智-2. bob(同企业普通成员)用这个"客服助手"聊 + 会话锁定

**对应**:SC-002、FR-002、FR-003(UX 面)、User Story 1。

**这步在验什么**:同企业的**普通成员**进库**看不到「新建」按钮**(只有管理员能建);但他能在对话窗**选用** alice 建的"客服助手";选定开聊后**这个会话锁定用它、没有"换智能体"的入口**。

**你该看到什么**:
1. **另开无痕窗口**,用 `bob` / `bob` 登录,进 **「智能体库」**。
2. **关键(FR-003 UX)**:bob **看不到「新建智能体」按钮**(他不是管理员)。但他**能在列表里看到「客服助手」**(同企业可见)。
3. bob 进 **Workspace** → 点 **+ 新会话** → 弹出的智能体选择器里**选「客服助手」**(下拉里它标「本企业」)→ 点「开始对话」。
4. 发一条消息,比如「帮我查下退款要多久?」—— **回复应符合那段提示词**:**中文、简短、客服口吻**(这就是 SC-002 / US1:选的角色真的生效了)。
5. **关键(FR-002 锁定)**:会话开始后,对话窗顶部显示**绑定的智能体名 + 「已锁定」**标记,**界面上没有任何"换/切换/更换智能体"的入口**;新建另一个会话才能重新选。

> 如果建会话失败(沙箱起不来等),选择器里会**明确报错、保持开着可重试**,不会静默卡死、也不残留半成品会话(spec Edge Case;前端 `Workspace.test.tsx` 有覆盖)。

---

## 智-3. 跨企业隔离:别人看不到、用不了"客服助手"〔dev 单企业 → 执行者代跑负向〕

**对应**:SC-003、FR-005、User Story 3。

**这步在验什么**:**另一个企业**的用户在「智能体库」里**看不到** alice 建的"客服助手";就算他**猜到/攥着**这个智能体的 id 想拿去建会话,也会被服务端**拒掉**(403/404)。

**你该看到什么**:
- **若有第二个企业的账号**:用它登录 → 进「智能体库」→ 列表里**没有"客服助手"**(只有他自己企业的);拿"客服助手"的 id 去建会话 → **被拒**。
- **dev 默认只有一个企业 `ent-demo`** —— 造第二个企业要在 Keycloak 多开一个 Organization,dev 没默认配。**故此条由执行者用直连 BFF 的负向 curl 代跑**:伪造"另一个企业前缀"、或用一个**本企业不可见的 agent_id**去建会话 → 服务端 **403**,且**不创建任何 managed 会话**。

> **说明**:双企业的完整端到端隔离演示需要多一个 KC org;dev 默认单企业 ent-demo,所以这条用执行者的负向验证代跑。隔离的**红线不变式**(列表只含本企业可见项、建会话校验 agent 归属、跨企业 agent_id 被拒)在 BFF 单元测试里已钉死:`tests/gateway/bff/test_agents.py`(`test_list_filters_per_enterprise_and_strips_prefix` / `test_session_create_rejects_other_enterprise_agent` / `test_session_create_rejects_unknown_agent`)。

<details><summary>怎么做(命令,执行者跑)</summary>

```bash
# 前提:用真实登录会话拿到 BFF 会话 cookie(略;同 9a 负向段做法)。
# A) 用"本企业看不到的 agent_id"(模拟他企业 agent)建会话 → 403/404,且不建 managed 会话:
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8090/v1/ws/sessions \
  -H "X-CSRF-Token: <csrf>" -b "<session-cookie>" \
  -H "Content-Type: application/json" -d '{"agent_id":"ag_other_enterprise_or_unknown"}'
# 期望:403(或 404);后台 omnigent 无新增 /v1/sessions 调用。

# B) 普通成员伪造"企业前缀分隔符"想越界造他企业角色 → BFF 400,绝不打到 omnigent:
#    (前缀只能由 BFF 据已认证会话写入;客户端供 U+001F = 伪造,直接拒。)
printf 'name=%s\n' "ent-bbb"$'\x1f'"伪造助手"   # 仅演示载荷里的 U+001F
# 单元测试已钉死:tests/gateway/bff/test_agents.py::test_create_rejects_client_supplied_sep_prefix_forgery
```
</details>

---

## 智-4. 非管理员被服务端拒(不靠前端藏按钮)〔执行者代跑〕

**对应**:SC-004、FR-003、FR-008、User Story 2 验收 2。

**这步在验什么**:**安全不靠前端藏按钮兜底**。就算 bob(普通成员)绕过界面、**直接拿他自己的登录会话去调创建接口**,服务端的统一授权 `can()` 也会**拒绝**(403)。

**你该看到什么(执行者把结果摆给你)**:bob 带着他**真实的登录会话** + CSRF 头,直接 `POST /v1/ws/agents` 建智能体 → 网关回 **403**(理由含 `enterprise-admin`),**根本没打到 omnigent**、**没建任何 agent**。

<details><summary>怎么做(命令,执行者跑)</summary>

```bash
# bob(普通成员)带真实会话直接调创建接口 → 403(服务端 can() 拒,不靠前端):
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8090/v1/ws/agents \
  -H "X-CSRF-Token: <bob-csrf>" -b "<bob-session-cookie>" \
  -H "Content-Type: application/json" -d '{"name":"bob想建的"}'
# 期望:403  {"reason":"... requires enterprise-admin"};后台 omnigent 无新增 /v1/agents POST。
```

> 单元测试已钉死(无需起栈即可证):
> - `tests/gateway/bff/test_agents.py::test_non_admin_create_403_no_omnigent`(非 admin 建 → 403 且**不打到 omnigent**)
> - `tests/authz/test_can.py`(`AGENT-CREATE-MEMBER-DENY` 普通成员被拒;`PADM-AGENT-CREATE` 连**平台管理员**调 agent:create 也被拒,必须走 `/admin/*`,证明 agent 规则永不被平台管理员触达)
</details>

---

## 智-5. 企业默认智能体与编辑/删除边界

**对应**:SC-005、FR-006、FR-001。

**这步在验什么**:企业库展示 minimax、debby、codex、polly 四个默认本企业智能体，不展示内置模板卡片入口；管理员与普通成员的编辑/删除能力按后端授权区分;刷新后默认卡片状态稳定。

**你该看到什么**:
1. **你该看到什么**:智能体库里有 minimax、debby、codex、polly 四个"本企业"智能体,不再并列展示"内置"模板卡片。管理员能编辑 debby,能删除 polly;刷新后结果保持。普通成员没有编辑/删除入口。
2. 管理员对 debby 执行编辑、对 polly 执行删除后刷新列表;行为仍按策略持续生效，不会被重建流程自动恢复。
3. non-admin（普通成员）在列表与接口层都看不到编辑/删除入口;服务端拒绝编辑/删除请求。

> 单元测试佐证:`tests/gateway/bff/test_agents.py::test_default_enterprise_agent_templates_are_fixed_four`(默认四个本企业卡片),`tests/gateway/bff/test_agents.py::test_edit_builtin_rejected`/`test_delete_builtin_rejected`(内置拒绝编辑/删除),`tests/gateway/bff/test_agents.py::test_edit_own_agent_reposts_same_name_with_new_fields_and_audit`/`test_delete_own_agent_proxies_and_audits`(本企业 own 的编辑/删除路径)。

---

## 7. 收尾:停掉整套环境

**这步在验什么**:一条命令能不能干净地停掉整套环境,**包括那些动态拉起来、不在 compose 文件里的 `omnigent-managed-*` 沙箱容器**(否则它们会残留、占资源)。

<details><summary>怎么做(命令)</summary>

```bash
make ws-down
# 它会按反向顺序停:网关进程 → omnigent server → Keycloak/MinIO,
# 最后把残留的 omnigent-managed-* 沙箱容器一并删掉(它们是动态拉起、不在 compose 里的)。
# (前端不用单独停 —— 它是网关在 8090 同源发的,没有独立进程。)
```
</details>

---

## 附录:命令速查 / 怎么做汇总

| 动作 | 命令 |
|---|---|
| 起整套栈(含 build+发前端,等就绪) | `make ws-up` |
| **唯一入口(浏览器开)** | **http://localhost:8090**(网关同源发前端,无需单独起前端) |
| 改了前端代码要生效 | `make fe-build`(重 build dist;真·热更新延后) |
| 停整套(含清理 managed 沙箱) | `make ws-down` |
| 只补建/置备测试用户和企业(幂等) | `make provision-orgs` |
| 自编译 omnigent 镜像 | `scripts/omnigent_build.sh dev` |
| 起/停 omnigent | `make omnigent-up` / `make omnigent-down` |
| 看活跃沙箱容器 | `docker ps --filter name=omnigent-managed-` |
| 看自编译镜像 | `docker images \| grep omnigent` |

**测试账号**:`alice` / `alice`(企业管理员)、`bob` / `bob`(普通成员),同属企业 `ent-demo`(邮箱域 `acme.test`)。
**地址**:**入口/网关 `:8090`(浏览器只开这个)**、Keycloak `:8080`(登录中转)、omnigent `:8900`。(不再有独立的前端 `:5173` —— 网关 8090 同源发前端。)
**订阅 token**:`secrets/omnigent.token`(不进代码仓;ws-up 自动读出注入为 `CLAUDE_CODE_OAUTH_TOKEN`)。

> **哪些是 owner 亲自做、哪些执行者代跑**:
> - **你(owner)亲自做**:第 0 步起栈、第 1~3 步浏览器登录 + 点击 + 双用户隔离(SC-001/002/003 的核心);**智能体库**第 智-1 步(alice 建客服助手)、智-2 步(bob 选用 + 锁定)、智-5 步(企业默认卡片与编辑/删除边界)。
> - **执行者代跑、把结果摆给你**:第 4 步(沙箱容器)、第 5 步(改码重编译生效)、第 6 步(负向 curl);**智能体库**第 智-3 步(跨企业隔离,dev 单企业故负向 curl 代跑)、智-4 步(非管理员直调接口 → 403)。
