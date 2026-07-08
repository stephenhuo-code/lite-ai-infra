# S1 DoD 状态 / go-no-go 证据底稿(2026-07-08)

> 给 owner 签字用。原则:**证据先于断言**(宪法 §3.2),每条附实测。
> 分支:`plan9a-omnigent`(= `main`,已快进同步)。对照 S1 design §7 DoD、§1 出口表、§9.3 计划序。

## 一句话现状

**S1 的阻塞性出口(①②③⑤ + 服务化)已全部达成并合并 main、各自过 live 验收**;出口④(Dev Workspace)本就是"唯一降级 · stretch · 不阻塞 DoD",且被 **Plan 9a 大幅超额交付**(omnigent 对话 + 智能体库 + 模型配置/每 provider harness),9b(dev workspace 全貌)推迟。

**但 DoD 的"集成全绿 + CI 远端绿"一项当前 ❌ 红**:远端 CI 的 `integration` job 因**陈旧集成测试**(仍按 ADR-024/025 之前的 `e-0001/g-0001` 组模型 + 老 realm 写、落地后未更新)全线失败;`build` job 曾因一个 macOS 专有路径的测试失败,**本底稿一并修复**。这是**测试欠债,非产品破坏**(产品的 GUI/omnigent live 验收均通过)。

**建议**:仿 S0"closed with carry-over"——**S1 以带 carry-over 关闭**,把"集成测试套件对齐 ADR-024/025 + CI 远端复绿"作为**移交项**(S2 首周或独立 cleanup 任务);或 owner 选择先补齐集成测试再签清洁 go。二选一由 owner 拍板。

---

## 出口对照(design §1 / §9.3,证据到 plan/ADR)

| 出口 | 状态 | 证据 |
|---|---|---|
| ① 100GB 一行命令清洗(多模态)→ Lance | ✅(1GB 档机制级关闭;100GB 边界移交 S2a) | ADR-014 门禁 **2026-06-12 GO**(早于 06-17 硬时限);Plan 5 data-pipeline-service 真 DJ 端到端 + dev/prod parity(`s1-plan5`);Spike 1/2 真 OSS 内网 GO(`spikes/*/RESULTS-aliyun.md`) |
| ② Gravitino 可查 | ✅ | Plan 4 metadata-service 合并(契约先行 + Gravitino docker + 注册/查询 + 集成);catalog 为位置真相源([ADR-023](../../adr/ADR-023-catalog-driven-datasets.md));metalake `e_XXXX`/catalog `data`/schema `datasets`([ADR-016](../../adr/ADR-016-gravitino-tenancy-mapping.md)) |
| ③ 薄 can() 企业隔离 | ✅ | S0 交付 + S1 接入管线入口与两服务;owner 归属模型([ADR-024](../../adr/ADR-024-owner-based-dataset-ownership.md));单测覆盖(`tests/authz/`) |
| ⑤ 真 GUI 经 API 端到端调通([ADR-019](../../adr/ADR-019-exit5-gui-bff-resequence.md) 重定义) | ✅ **已关闭(2026-06-24)** | Plan 8 React/Vite 控制台 + 真浏览器 e2e(登录→列→上传→建作业→终态);Plan 6 BFF(真 KC code+PKCE 全链路,一键验收 7/7);Plan 7 上传后端 **真阿里云 OSS R1–R10 10/10**([ADR-020](../../adr/ADR-020-dataset-upload-mechanism.md)) |
| 新 · 服务化 | ✅ | Plan 3/4/5 契约先行(`contracts/openapi/*.yaml` → codegen → 实现),gateway 反代壳 + 漂移守卫 CI |
| ④ Dev Workspace | ✅ **超额**(9a)· ⏳ 9b 推迟 | 原为 stretch code-server 半天版;实际由 **Plan 9a** 交付 omnigent 集成 + Workspace 对话窗(多用户/隔离/fork 自编译,[ADR-026](../../adr/ADR-026-omnigent-integration.md))+ 智能体库([ADR-027](../../adr/ADR-027-agent-library.md))+ 每企业模型配置·每 provider 独立 harness([ADR-028](../../adr/ADR-028-per-enterprise-model-credentials.md));真机验证 minimax/deepseek 真 key 流式通。9b(左树/文件/终端/MCP 数据工具)推迟 |

## 验收 B 段(自动化,2026-07-08 实测)

```
make test        → 324 passed, 17 deselected(单元,-m "not integration";含本底稿修复的 provision --help 测试)
make lint        → layering KEPT + Contracts: 1 kept, 0 broken(import-linter + §8 grep 护栏 exit 0)
前端  npx vitest run   → 89 passed；npx tsc --noEmit → 无错
fork  test_provider_harnesses.py → 全绿(锁 minimax/deepseek harness 7 处触点)
```

## CI 远端状态(main 最近一次 push,run 28912589136)❌

| job | 结果 | 根因 |
|---|---|---|
| `build`(单元 + lint + 护栏 + codegen) | ❌ → **本底稿修复** | `tests/scripts/test_provision_default_agents.py::test_script_help_runs_as_direct_cli` 硬编 `UV_CACHE_DIR=/private/tmp/uv-cache`(macOS 专有,本机绿)→ Linux CI `Permission denied`。**修复**:改用 `tempfile.mkdtemp()`(可移植)。其余 323 全绿 |
| `integration`(`make test-integration`) | ❌ **陈旧欠债(carry-over)** | 见下表——集成测试套件在 ADR-024(owner 模型)/ADR-025(KC Organizations、移除组层)落地后**未更新**,仍按老 `e-0001/g-0001` 组模型 + 老 realm 断言。deps(KC+MinIO)本身就绪,失败全在测试期望 |

### integration 失败根因(需对齐当前架构)
| 测试 | 现象 | 应改为 |
|---|---|---|
| `test_gateway_proxy.py:72/84` | `memberships[0]` IndexError(空成员) | 新 realm 用 KC Organizations(企业=alias,如 `ent-demo`),不再 `e-0001/g-0001`;固件/断言按 ADR-025 更新 |
| `test_raw_upload_e2e.py:23` | 期望 `e-0001/g-0001/raw/…`,实得 `e-0001/u-a/raw/…` | owner 路径模型(ADR-024):`e-XXXX/{user}/raw/…` |
| `test_data_pipeline_e2e.py:28` | `JobSpec.__init__() got multiple values for 'source_dataset'` | 契约/构造签名漂移,按当前 `data-pipeline.yaml` 更新 |
| `test_bff_oidc.py:98/130` | `prepare` 403≠202;KC 未返回 code | 新 realm/client(ADR-025)+ owner 授权门;固件更新 |

> 说明:**本地 `make test` 默认 `-m "not integration"` 跳过集成**,故该欠债此前未被发现。产品侧无破坏——出口⑤/⑨a 均有**独立 live 验收**通过(真 GUI 全链路、真 OSS R1–R10、omnigent 真机对话)。

## DoD 清单镜像(design §7)

- [x] ADR-014 门禁关闭 —— **2026-06-12 GO**(证据:`2026-06-11-s1-week1-gate.md` + ADR-014)
- [x] 出口①②⑤ + 服务化验收命令实测通过 —— Plan 3–8 全 ✅ 合并 + 各自 live 验收(见上表)
- [~] 单元 + 集成全绿;import-linter + §8 护栏 + codegen 绿 —— **单元 ✅ / lint ✅ / codegen ✅;集成 ❌(陈旧,carry-over)**
- [x] code review 过 —— Plan 3–8 各有独立评审(0 Crit);9a/agents/model-config 系列有 spec/design/PROBE + 单测护栏(9a 合并走了 owner 直合,见 §合并记录)
- [~] CI 远端绿 —— **build 本底稿修复后应转绿;integration 待欠债清理**
- [ ] go/no-go 签字 —— **owner 动作(本底稿即为其证据)**

## 关闭路径(owner 二选一)

1. **带 carry-over 关闭(推荐,仿 S0)**:签认 S1 关闭,把"**集成测试套件对齐 ADR-024/025 + CI 远端复绿**"列为移交项(S2 首周或独立 cleanup 任务,建议单独 plan)。理由:阻塞性出口均 live 验收通过,红的是测试期望而非产品;S0 亦以 carry-over 关闭(exit① 移交 S1)。
2. **先补齐再签清洁 go**:先做一轮集成测试更新(约 4 个文件:gateway_proxy / raw_upload_e2e / data_pipeline_e2e / bff_oidc,按 ADR-024/025 改固件与断言)→ CI 远端全绿 → 再签 go/no-go。

> 无论哪条,`build` job 的 macOS 路径修复已在本底稿一并落地(下方提交)。

## 本底稿附带的修复
- `tests/scripts/test_provision_default_agents.py`:`UV_CACHE_DIR` 由硬编 `/private/tmp/uv-cache` 改 `tempfile.mkdtemp()`(可移植)→ 解 CI `build` job 红。本地 `uv run pytest tests/scripts/test_provision_default_agents.py -q` → `2 passed`。
