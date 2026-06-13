# ADR-017: 计划任务用 checkbox 拆分 + 执行时实时更新完成状态

- 状态：Accepted（2026-06-14,owner)
- 决策人：owner
- 相关：constitution §3.4(计划先行)/ §3.3(证据先于断言);ADR-015(计划必含 runbook);superpowers writing-plans / executing-plans / subagent-driven-development(checkbox 跟踪本是其约定)

---

## Context

实现计划若任务粒度不清、或执行中不更新状态,会出现:进度不可见、不知做到哪、中断后难续、"做完一批才补勾"导致状态与实际脱节(尤其 headless / 长自主运行时)。superpowers 的 writing-plans/executing-plans 本就用 `- [ ]` checkbox 跟踪,但需要写进宪法成为硬纪律。

## Decision

写进 constitution §3.4:

1. **计划必须按 checkbox 拆分**:每个任务/步骤用 `- [ ]`,粒度到"可单独勾选/验证"(配合 writing-plans 的 bite-sized 步骤)。
2. **执行时必须实时更新完成状态**:每完成一步即勾 `- [x]`,并用 TodoWrite 同步 `in_progress`/`completed`;**不得做完一批才补勾、不得全程不更新**。
3. 目的:进度随时可见、可中断可续、状态与实际一致(证据先于断言的过程版)。

## Consequences

- 正面:进度透明;中断/换会话/headless 后可凭 checkbox 续接;reviewer/owner 随时看到"做到哪"。
- 代价:执行中多几次勾选/TodoWrite 调用(开销可忽略)。
- 既有:Plan 1–4 已用 checkbox;本 ADR 把"实时更新"从习惯升为硬纪律。
