# S0 DoD 状态 / go-no-go 证据底稿（2026-06-10,06-11 按 ADR-014 更新）

> 给团队签字用。原则:证据先于断言(宪法 §3.2),每条附实测输出。
> 分支:`s0-foundation`。

## 一句话现状

**S0 按 [ADR-014](../../adr/ADR-014-s0-exit1-carryover-to-s1.md) 以 "closed with carry-over" 关闭**:
出口②③④ PASS + 全部本地工作闭环并过 code review;出口①(数据 Spike,被云环境/100GB
数据集两个外部前置卡住)**移交 S1 第一周入口门禁**(S1 第 3 工作日硬时限,详见 ADR-014)。
签认 ADR-014 = 签认本次关闭。

## 出口对照(design §5.3)

| 出口 | 状态 | 证据 |
|---|---|---|
| ② Keycloak 26.6.2 token 带 `groups` claim | ✅ | 本地 compose 取 token → `['/e-0001/g-0001/members']`;集成测试真验签 `2 passed` |
| ③ Gateway 解析 enterprise_id/group_id | ✅ | 真 token(验签开启)→ `/v1/me/orgs` 返回 `e-0001/g-0001/member`;跨企业 DELETE → 403 cross-enterprise;审计落 MinIO `audit/2026/06/09/...jsonl` |
| ④ contracts 代码生成跑通 | ✅ | `make gen` + CI freshness gate;`git diff --exit-code libs/contracts_gen/` 无 diff |
| ① 数据 Spike 1/2 PASS | ❌ **未执行** | 本地 harness 彩排通过(见下);真判据(OSS 延迟/100GB OOM 边界)需阿里云 |

## 验收 B 段(自动化,2026-06-10 实测)

```
uv run pytest -q                       → 25 passed, 2 deselected
uv run pytest -q -m integration        → 2 passed(真 MinIO 写读 + 真 Keycloak 验签)
uv run lint-imports                    → Contracts: 1 kept, 0 broken
bash scripts/ci_guards.sh              → exit 0
make gen && git diff --exit-code …     → 无 diff
```

## Code review(superpowers:requesting-code-review,2026-06-10)

范围 `main(39d9218)..123362b`,judgment **"With fixes"**;修复已落 `fc5dbb4`:

| 级别 | 发现 → 处置 |
|---|---|
| Critical#1 | `x-test-claims` seam 默认开 → **翻转为默认关**(default-deny),回归测试锁死 |
| Important#2/3 | JWT 不验 issuer/audience、JWKS client 每请求新建 → env 可强制校验 + lru_cache |
| Important#4 | 宪法 §1.2 typed IDs 缺失 → `EnterpriseId/GroupId` NewType;**mypy CI 门禁记 S1** |
| Important#5 | README §5/§6 过时 → 已更新 |
| Minor#6/9/10 | grep 守卫启发式偏松 / 审计 key 含 `:` / dev-secret 上云需轮换 → **记账,S1 处理** |
| Minor#7/8/11 | Makefile exit-5 掩码 / seam 坏 JSON 500 / owner=None 无注释 → 已修 |

Plan 级教训(反馈给 S1 计划):seam 默认开、str 型 ID 两个坑都是 plan 原文带进来的。

## Spike 账目

| Spike | 状态 |
|---|---|
| 数据 Spike 1(Lance)| 本地 harness ✅(MinIO 基线:写 40.5MB/s、列裁剪 0.004s vs 全扫 0.089s);**阿里云待跑** |
| 数据 Spike 2(DJ+Ray)| 本地 harness ✅(8 进 4 出,坏样本全滤,幂等);**阿里云待跑**;两个上云坑已写进 spikes/README |
| Spike A(Organizations claim)| 本地 ✅ PASS(双组全路径 ✓;变更 98ms 反映 ✓;stale 窗口=300s);结论已回写 ADR-010 附录 C;**阿里云复验待** |
| Spike B(Cerbos seam)| ✅ PASS(同 can() 签名调 Cerbos,AC-1/2/6/9 与 v1 逐条一致,app.py 零改);结论已回写 ADR-011 附录 |
| Spike C(真 OSS+STS)| 逻辑已被任务 9 MinIO 集成覆盖;真 OSS 待跑(IaC 已备:deploy/test/terraform) |

## 关闭路径(ADR-014)

1. 团队签认 ADR-014(Proposed → Accepted)→ **S0 即关闭(carry-over)**
2. 移交 S1 第一周门禁:数据 Spike 1/2 + Spike A 阿里云复验 + Spike C 真 OSS
   (前置:阿里云最小环境开通 + 100GB 数据集落位 OSS;S1 第 3 工作日内出结论,
   否则触发 design §5.4 原动作,不得二次顺延)

## DoD 清单镜像(plan §F,按 ADR-014 口径)

- [ ] B + C 全部命令实测通过 —— B ✅;C 的②③ ✅;**① 按 ADR-014 移交 S1**
- [ ] 出口①②③④ 全 PASS —— ②③④ ✅;**① carry-over(非 PASS,见 ADR-014)**
- [x] Spike A/B 结论已回写 ADR —— A→ADR-010 附录 C(本地;云复验随 S1)、B→ADR-011 附录;数据 Spike 结论随 S1 门禁回写
- [x] code review 过
- [x] plan 任务 1–10 checkbox 全 `[x]`、commit 齐
- [ ] 团队 go/no-go 签字 —— **= 签认 ADR-014**
