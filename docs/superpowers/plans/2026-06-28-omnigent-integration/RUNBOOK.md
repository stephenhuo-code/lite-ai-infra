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
> - **你(owner)亲自做**:第 0 步起栈、第 1~3 步浏览器登录 + 点击 + 双用户隔离(SC-001/002/003 的核心)。
> - **执行者代跑、把结果摆给你**:第 4 步(沙箱容器)、第 5 步(改码重编译生效)、第 6 步(负向 curl)。
