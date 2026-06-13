# ADR-015: 计划必须含"手动验收 runbook"

- 状态：Accepted（2026-06-13，owner)
- 决策人：owner
- 相关：constitution §3.4(计划先行)/ §3.3(证据先于断言);superpowers writing-plans / verification-before-completion

---

## Context

S1 执行中多次出现"计划写了实现步骤,但 owner 不知如何手动验收/复现"的摩擦(如 Plan 3 起服务、看 Swagger、端到端调用)。自动化测试证明"代码对",但 owner 需要一份**不读代码就能照抄、亲眼看到行为**的命令序列来验收——这与 §3.3"证据先于断言"同源,只是面向人而非 CI。

## Decision

写进 constitution §3.4:**每份实现计划必须包含"手动验收 runbook"**——可照抄的命令序列(起服务 / 调接口 / 看 Swagger / 查产物等)+ 每步期望证据;让人不读代码即可手动复现验收。**无 runbook 的计划不算完成。**

runbook 可随计划演进更新(如 Plan 3 从"3 终端"更新为 `make up` 一键);新服务计划复用前序 runbook 模板。

## Consequences

- 正面:owner 可独立验收;降低"我怎么测"往返;runbook 沉淀为各服务的操作文档。
- 代价:每份计划多一节(通常 ~20 行),可接受。
- 既有计划:Plan 1/2/3 已补 runbook;后续计划在 writing-plans 阶段内建此节。
