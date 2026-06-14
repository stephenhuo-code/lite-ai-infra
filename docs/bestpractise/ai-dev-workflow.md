# AI 开发流程经验(superpowers + headless + 强制人工验收)

> 来源:S1 Plan 3/4 实战复盘(2026-06)。沉淀成可复用 playbook。配套硬纪律见 constitution §3.4、ADR-015/016/017。

## 0. 一句话

**让 AI 高速产出,用"隔离验证"兜底正确性。** AI 写得快、覆盖广,但**对自己的盲点不可见**;流程的价值不在让 AI 更聪明,而在每一步都有**独立于实现者**的闸门(契约、测试门禁、人工 runbook、独立 reviewer)。

## 1. 整体流程

```
brainstorming(意图/方案,先发散)
  → spec(设计定稿,分节确认)+ 争议走 ADR
    → writing-plans(任务级 checkbox + 每步 TDD + 必含手动 runbook)
      → execute(交互 或 headless;每步实时勾选 + 全绿门禁才进下一步)
        → 隔离审查(① 人跑 spec/runbook ② 独立 reviewer code-review)
          → 修 Critical/Important → 合并
```

每个箭头都是一道闸,**不跳步、不假绿**(宪法 §3.3 证据先于断言)。

## 2. 实战最大的一条:机器自评 ≠ 验证

Plan 4 由 headless(`claude -p`)自主跑完 7 个任务,且**自己跑了一轮 code review**、78 单元 + 7 集成全绿。看起来"完成了"。但随后:

- **独立 reviewer 子代理**逮到 **I-1**:无 `owner_group` 的 fileset → `p["owner_group"]` KeyError → **500 而非 fail-closed 403**。
- **owner 手动跑 runbook**(固定名 `cc3m`,与探针建的撞)逮到 **409 bug**:重复注册未接住 Gravitino 409 → **逃逸成 500**。

两个都是真 bug,**自动测试 + headless 自评全没逮到**——因为:单测的 fake 不模拟冲突、集成测试用 `uuid` 名永不撞、机器 review 自己的代码有盲区。

**结论(ADR-017 落为硬纪律)**:计划完成 ≠ 通过。合并前必须两道**隔离**审查:
1. **人**:照 runbook 手动验收 + 对照 spec 逐 task 核(机器不替代)。
2. **独立 reviewer**:`superpowers:requesting-code-review` 派**非实现者**子代理审 `main..HEAD`。

> 这条今天就回了本:两个会进生产的 500 在合并前被挡下。

## 3. headless 执行:何时用、怎么用、边界

**何时用**:计划已审定、任务确定性高、可无人值守。用 `headless-plan-runner` skill / `run-plan-headless.sh`。

**怎么用**(三个要点,踩坑换来的):
- **订阅模式**:脚本先 `unset ANTHROPIC_API_KEY`,否则走 API 计费报 `Credit balance too low`(shell 启动文件里硬编码的 key 要注释掉)。
- **流式 + 落日志**:`claude -p --verbose --output-format stream-json | tee log`,另开 `tail -f` 或 `watch git log`(每 task 一 commit)看进度。
- **合并前停**:headless 跑完只 push + 自评 review,**合并留给人**。

**边界(别踩)**:
- headless **无法中途纠偏**——探索性/有未知判断的任务别用 headless,用交互(Plan 4 Task 1 探针就是交互里边跑边适配的)。
- headless 的"自评 review"**不算数**,必须叠加 §2 的隔离审查。

## 4. probe-first:未知外部依赖,先探针再写计划

Gravitino 的真实 REST/版本/行为我们不确定。**没把猜的 API 写进计划**,而是 Plan 4 Task 1 = 探针:起真服务、curl 跑通全链、把响应包络/字段/坑写进 `RESULTS.md`,后续代码**以实测为准**。

回报:探针当场发现计划没覆盖的两个坑——FILESET catalog 建 schema 时校验 S3(**bucket 必须先存在 + 强制 path-style**)。若等集成阶段才撞,排查成本翻倍。

**纪律**:对不确定的外部系统,计划第一个 task 就是"探针 + 钉死事实",别让推测的 API 漏进实现。

## 5. 决策纪律:争议走 ADR,地基改动先批判后批准

- **每个有争议的设计选择落 ADR**(ADR-011/016 授权与租户映射;ADR-015/017 流程纪律)。正文永远是最新版,历史看 ADR + git。
- **地基级改动**(如"把 group 从隔离单元拿掉")**先批判再动手**:用 product-architect 顾问做 blast-radius 分析,确认是真需求还是偏好。Plan 4 期间这一步**避免了一次重开已关闭 S0 地基的返工**——结论是保留 group、把 user/role grant 留作 v2 叠加层。
- **API 优先**:服务的契约是稳定面,不裸传/暴露底层(Gravitino)——metadata-service 是其上的薄 PEP,隐藏 metalake、can() 过滤、领域投影。

## 6. 计划纪律(写进 constitution §3.4)

- **checkbox 拆分 + 实时勾选**:每步 `- [ ]`,做完即 `- [x]` + TodoWrite 同步——进度可见、可中断可续(headless 跑完忘回填就是反例,见 ADR-017)。
- **每份计划必含手动验收 runbook**(ADR-015):可照抄命令 + 期望证据,让人不读代码也能复现验收。§2 的人工验收靠它。
- **全绿门禁**:每 task 结束跑该项目的测试/lint/构建全绿才进下一步;失败走 systematic-debugging 定位根因,不打补丁猜。

## 7. 反模式清单

| 反模式 | 正解 |
|---|---|
| headless 跑完 = 完成 | 必过人工 runbook + 独立 reviewer |
| 机器审自己的代码当审查 | 隔离审查(独立子代理 / 人) |
| 把猜的外部 API 写进计划 | probe-first,实测钉死 |
| 测试用 uuid/ fake 永不撞边界 | 加冲突/缺字段/越权等 fail-closed 用例 |
| 地基改动直接动手 | 先批判(blast radius)+ ADR |
| 计划做完一批才补勾 | 实时勾选 + TodoWrite |
| 裸传底层系统的 API | 自有契约 + 薄 PEP 投影 |

## 8. 上手清单(下个计划照做)

- [ ] brainstorm → spec 分节确认;争议 → ADR
- [ ] writing-plans:任务级 checkbox + 每步 TDD + 手动 runbook;不确定外部依赖 → 第一个 task 设探针
- [ ] 执行:交互(有未知)或 headless(确定);实时勾选 + 全绿门禁
- [ ] 完成后:人跑 runbook + 独立 reviewer;修 Critical/Important
- [ ] CI 绿 → owner 确认 → 合并 → 回标 spec/计划 checkbox
