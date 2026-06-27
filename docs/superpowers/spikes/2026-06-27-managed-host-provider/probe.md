# P0a 探针:omnigent managed-host 在我们 infra 上的 launch/auth 机制

**日期**:2026-06-27 / 28　**结论**:可行,走决策 **(b) 自写最小 docker SandboxLauncher 插入 omnigent 的 launcher-factory 接缝**。

## 调研事实(file:line)

- omnigent managed host = `host_type="managed"` 的 server-launched 沙箱(`omnigent/server/managed_hosts.py:1-22`)。**host 用 server 签发的 launch token 回连认证(`X-Omnigent-Host-Token`),用户凭据不进沙箱握手**(`host_store.py:525 register_managed_host / 611 resolve_launch_token`;`server/routes/host_tunnel.py:121-196`)。→ **这正好解了 header-auth 下容器化 host 怎么认证的问题:用 launch token,不用用户凭据。**
- 内置 provider(`managed_hosts.py:35,132-143`):`lakebox|modal|daytona|boxlite|cwsandbox|islo|e2b|openshell|kubernetes`。
  - **没有"普通 docker run on this host"provider。**
  - `boxlite` local 模式 = **microVM,需 KVM/hypervisor + `pip install omnigent[boxlite]`**(`onboarding/sandboxes/boxlite.py:362-366` 明确 `/dev/kvm`;macOS 用 Virtualization.framework)。比普通 docker 重,且 prod ECS 是否有嵌套虚拟化依实例类型。
  - modal/daytona/islo/e2b/cwsandbox = 云沙箱 SaaS(需各自 API key);openshell = k8s gateway。
- **接缝(关键)**:`ManagedSandboxConfig` 带 `launcher_factory`,可经 `create_app(sandbox_config=ManagedSandboxConfig(server_url=..., launcher_factory=lambda: MyLauncher(...), token_ttl_s=...))` 注入自定义 launcher(`managed_hosts.py:24-100`)。managed-only launcher 实现 `prepare/provision/run/terminate`,CLI-bootstrap 原语默认报 capability error 无需覆写。
- omnigent 负责 managed-host **生命周期**:token 签发/owner 绑定/sandbox 死了按同 host_id 重建/session↔host 绑定存活(`managed_hosts.py:11-15`)。我们只需提供"起/停一个 host 容器"的后端。

## 决策(b):自写 docker SandboxLauncher

- 写一个最小 `DockerSandboxLauncher(SandboxLauncher)`:`run` = `docker run -d omnigent-host:<tag>`(注入 server 给的 launch token env `OMNIGENT_HOST_TOKEN` + 该用户订阅凭据 from vault + server_url),`terminate` = `docker rm -f`。`prepare/provision` 最小实现。
- 接入二选一(Phase 3 定):
  - **(b1)** patch-queue 给 omnigent 加一个 `provider: docker` 到 `parse_sandbox_config` + 内置该 launcher → 纯 YAML 配置,prebuilt server 镜像可用(只加配置 `sandbox: provider: docker`)。**首选**(贴 patch-queue 模型、不改 server 启动方式)。
  - **(b2)** 自写 server 入口调 `create_app(sandbox_config=...)` 传 launcher_factory。更灵活但要换 server 启动命令。
- server 容器需能 `docker run`(挂 `/var/run/docker.sock`)。dev macOS + prod ECS 都是普通 docker,**不需 KVM、不依赖云 SaaS**。
- 收益:复用 omnigent 原生 managed-host 全套(token 认证解 header-auth、owner 绑定、重建、session 绑定)+ 普通 docker 后端 + dev/prod 同机制。

## boxlite 实证被堵(owner 一度想用 → 验证后否决,记 vNext)

owner 曾倾向 boxlite(微虚拟机强隔离)。**实测确认在"全容器化 server"前提下跑不起来**:
- `docker run alpine ls /dev/kvm` → **容器内无 /dev/kvm**(Docker Desktop macOS 不给容器嵌套虚拟化)。
- boxlite 是可选 extra(`pyproject.toml:125 boxlite = ["boxlite>=0.9.5,<1"]`),server 镜像未装(`import boxlite` → ModuleNotFoundError)。
- boxlite 自述 "local embedded micro-VMs (KVM/HVF)" —— server 是 Linux 容器,只能走 KVM,而容器里没 /dev/kvm。
- 标准阿里云 ECS 一般也不给容器嵌套 KVM。
→ **boxlite 需要:server 出容器(用宿主 HVF/KVM,破 parity)或 KVM 能力主机(裸金属/嵌套虚拟化实例,重)。owner 决策:记 vNext 硬化项(将来有 KVM 主机时上,顺带覆盖推迟的 sandbox 强隔离)。v1 走 (b) 普通 docker。**

## 否决

- **boxlite local(microVM)**:见上,实证被嵌套 KVM 堵;记 vNext。
- **云 SaaS provider(modal/e2b/...)**:把数据平台的 host 外包给第三方云沙箱,违自托管 + 数据隔离取向。
- **决策(c)纯 BFF 侧编排(计划默认)**:不用 omnigent managed-host,自己 docker run host + 自取 host token + 静态注册。可行但要重造 token/owner/重建逻辑,且 header-auth 下取 host token 仍绕不开 managed-host token API → 不如 (b) 干净。**改用 (b)。**

## 对计划的影响

- Phase 3(T6/T7)按 **(b1)** 重写:patch-queue 加 docker provider + DockerSandboxLauncher;server compose 挂 docker.sock + `sandbox: provider: docker` 配置;BFF 建会话走 omnigent 原生 managed-host(server 自动起/复用该用户 host),不再 BFF 直接 docker run。
- **P0b(流式)gate 在此之后**:要等 docker launcher 起得来真 session 才能验 server-launched 路径的流式 delta。
