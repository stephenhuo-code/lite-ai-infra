# ADR-014: S0 出口①(数据 Spike)移交 S1 第一周入口门禁 — S0 以 carry-over 关闭

- 状态：Proposed(团队签认后改 Accepted)
- 日期：2026-06-11
- 决策人：平台团队
- 相关：design §5.3(Sprint 0 出口)/ §5.4(里程碑表 06-13 行)/ §5.6(滑窗策略);constitution §7.4(改路线走 ADR);`docs/superpowers/plans/2026-06-08-s0-foundation.md`(DoD §F);`docs/superpowers/plans/2026-06-10-s0-dod-status.md`(证据底稿)

---

## Context

S0(06-06 → 06-13)四条出口中,②(Keycloak token 带 groups)③(Gateway 解析)④(契约代码生成)已全部 PASS 并有实测证据;**出口①(数据 Spike 1 Lance-on-OSS / Spike 2 Data-Juicer+Ray,100GB,阿里云)未执行**。

未执行的原因不是技术失败,而是两个外部前置未就绪:

1. **阿里云测试环境未开通**(费用决策保留中;IaC/runbook 已备好且 terraform validate 通过)
2. **100GB 图文数据集的可用性/位置未确认**(这是比开 ECS 更硬的瓶颈)

与此同时,本地已完成全部可去风险动作:两个 spike 的 harness 在本地彩排通过(Lance/MinIO 基线延迟已出;DJ+Ray 8 进 4 出全滤),并提前踩掉两个上云级故障(`uv run --with` 瞬态环境挂死 Ray worker;HF hub 启动外联挂起)。Spike A 本地 PASS(双组 claim/98ms 传播/stale=300s)、Spike B 完整 PASS(Cerbos seam,go)。

design §5.4 对 06-13 未达的预设动作是"**顺延 S0,可能砍 v1 范围**";本 ADR 选择另一条路,按 constitution §7.4 以 ADR 形式记录。

## Decision

1. **S0 于 2026-06-13 前以 "closed with carry-over" 关闭**:出口②③④ PASS;出口① 不判 PASS/FAIL,**移交 S1**。
2. **出口① 改为 S1 第一周入口门禁(blocking gate)**:数据 Spike 1/2(+顺带 Spike A 阿里云复验、Spike C 真 OSS)是 S1 数据管线任务(Argo DAG / 多模态处理 / Lance helper)的**前置**,spike 未出结论前管线实现不开工。
3. **门禁时限**:S1 第 3 个工作日(≈06-17)内 spike 必须出结论(PASS / 降级);届时仍被外部前置(云环境/数据集)卡住 → 触发 design §5.4 原动作(顺延评估 + 砍 v1 范围讨论),不得再次顺延滑动。
4. **前置动作随 S1 启动立即执行**:阿里云最小环境开通(runbook `docs/ops/2026-06-09-test-env-aliyun-keycloak-oss.md`)+ 100GB 数据集落位 OSS。
5. S0 各文档如实表述为 carry-over,**不得写"出口全 PASS"**。

## Consequences

### 正面
- S0 按期关闭,S1 不被外部前置空转阻塞;harness 就绪使 spike 执行成本已收敛到"改 env + 放大 + 记数"。
- 纪律完整:改路线有 ADR、有时限、有触发性回退动作,非"偷偷滑"。

### 负面 / 代价(接受)
- **S1 核心(100GB 管线 → Lance)在未验证假设上规划**;若 spike 出"降级"结论(Lance 延迟不达 → JindoFS/缓存;DJ OOM → 分片/spill),S1 中段需当场改方案——fallback 已预设,损失可控但非零。
- 06-13 里程碑表的"两数据 Spike PASS"字面未达,以本 ADR 为正式记录。

### 风险登记
| 风险 | 应对 |
|---|---|
| spike 在 S1 内继续被云/数据前置拖延 | 第 3 工作日硬时限 + 触发 §5.4 原动作(本 ADR 决策 3) |
| 降级结论冲击 S1 排期 | S1 滑窗动作已预设"砍数据子集量"(design §5.4 S1 行) |
| carry-over 先例被滥用 | 仅此一次;后续 sprint 出口移交一律重新走 ADR |
