# P1 探针结论:官方 managed + 自托管 docker + SDK harness + 流式

**日期**:2026-06-28　**结论**:✅ **跑通 → 采纳决策(b)**。官方 managed 流程 + 我们自写的 DockerSandboxLauncher 在自托管 docker 上端到端成立。

## 验证到的(端到端)
- omnigent server 容器化(`deploy/docker` 官方 compose,`--target runtime`)+ 加载 `sandbox:` 配置(`OMNIGENT_CONFIG=/config.yaml`)。
- `host_type=managed` 触发 server 经 **DockerSandboxLauncher** `docker run` 一个隔离 host 容器(`omnigent-managed-<id>`)。
- 容器内 `omnigent host` **注册回 server(ONLINE,0s)**。
- 发消息 → claude-sdk agent(进程内)→ 调 Anthropic → **流式 delta 回 SSE** + 落 `/items`。
- **凭据注入成立**:`ANTHROPIC_API_KEY` 经 `sandbox.docker.env` 注入沙箱,claude-sdk 用它调了 Anthropic(返回的是 Anthropic 的 "Credit balance is too low" 计费错误,证明 key 到位 + API 调通,仅余额不足)。

## 钉死的事实(写进 design/plan)
1. **官方部署**:`deploy/docker` compose(postgres + server runtime 镜像);server external-runner 模式,但**给 `sandbox:` 配置即支持 managed**(`entrypoint.py` → `parse_sandbox_config` → `create_app(sandbox_config=)`)。
2. **建 managed 会话契约**:`POST /v1/sessions` **JSON body** `{"agent_id": "...", "host_type": "managed"}`(host_id 必须空)。**不是** multipart form 的 host_type(那会被忽略)。agent 先经 multipart bundled create 注册(返回 `agent_id`)或启动 `--agent`。
3. **sandbox config**:`sandbox: {provider: docker, server_url: http://<server>:8000, docker: {image, network, env:[...]}}`。`env` = server 进程的 env 变量名,注入沙箱。
4. **server 镜像需 docker CLI**:runtime 镜像默认无 `docker`;DockerSandboxLauncher 靠 `docker` CLI 驱动挂载的 `/var/run/docker.sock` → **fork 的 Dockerfile runtime stage 加 docker 静态客户端**(已做)。server compose 挂 docker.sock。
5. **DockerSandboxLauncher 的 run_background 必须覆写**:base `run_background` 拼 `setsid nohup {command}`,而 start_host 的 command 带**内联 env**(`OMNIGENT_HOST_TOKEN=… omnigent host …`)→ `nohup VAR=val cmd` 在 POSIX sh 坏(nohup 不认 env 赋值)。覆写为内层 `sh -c` 让赋值生效(已做)。Modal/Daytona 靠 SDK 注入 env 无此问题,docker 内联才暴露。
6. **网络**:host 容器加入 server 的 compose 网络(`omniprobe_default`),用服务名 `omnigent:8000` 回连(实测 200)。

## 我们 fork 的改动(模型 C,要提交进 fork)
- `omnigent/onboarding/sandboxes/docker.py`(DockerSandboxLauncher,新)+ `__init__.py`/`managed_hosts.py` 注册 `provider: docker`(复用备份 patch 0004)。
- `omnigent/onboarding/sandboxes/docker.py`:覆写 `run_background`(内层 sh -c 修内联 env)。
- `deploy/docker/Dockerfile` runtime stage:加 docker CLI 静态客户端。

## 凭据:订阅可用(owner 是对的)——已验证真回复
- **claude-native + 订阅 token(`CLAUDE_CODE_OAUTH_TOKEN`)在 managed docker 容器里真回复**(实测回 "SUBSCRIPTION_OK",**不需 API 额度**)。omnigent 官方 managed 流程里 claude-native 终端正常(我早先手搓那次卡死是手搓问题,非官方流程)。
- **关键坑**:**别同时注入订阅 token 和 ANTHROPIC_API_KEY**——omnigent 检测到 API key 会配 apiKeyHelper,与订阅 token 冲突(claude TUI 报 "Both CLAUDE_CODE_OAUTH_TOKEN and apiKeyHelper set · auth may not work")→ 无回复。**只注入 `CLAUDE_CODE_OAUTH_TOKEN`**(`sandbox.docker.env: [CLAUDE_CODE_OAUTH_TOKEN]`,server 不带 ANTHROPIC_API_KEY)。
- 两种 harness/凭据都验过:
  - **claude-sdk + ANTHROPIC_API_KEY**:token 级流式 delta ✓,但需有额度的 API key(实测 key 无额度报 "Credit balance too low",链路通)。
  - **claude-native + 订阅 token**:真回复 ✓ **且流式 ✓**(用订阅,无需 API 额度)。
- **claude-native 流式已实证**(更正早先误判):executor 层 `supports_streaming()=False`,但 transcript forwarder 旁路把 MessageDisplay hook 写的 `message_deltas.jsonl` 增量 POST 成 `external_output_text_delta` → server 转 `response.output_text.delta` 走 SSE。实测发 "count 1..15" 收到 `response.output_text.delta`(消息块级,best-effort live preview;落库以 `response.output_item.done` 完成项为准)。**坑:这套 setup 里 delta 时序滞后**(在 `response.completed` 之后才到)——前端读流**别在 completed 处停**;粒度=消息块级(非逐 token)。
- **9a 采纳:claude-native + 订阅(流式)**。codex-native + codex 订阅机制对称(可后续加)。要更细/更低延迟的逐 token 流式才需 claude-sdk + 产品 key(留选项)。

## 决策
**采纳 (b) DockerSandboxLauncher**。Phase 1+ 按本结论正式化(fork 提交上述改动 + omnigent_build.sh + deploy compose + BFF 反代 + 前端对话窗)。owner 研判此结论后铺开。
