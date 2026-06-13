---
name: "headless-plan-runner"
description: "为一个实现计划生成可命令行执行的 headless 运行脚本(claude -p):自动 unset API key 走订阅模式、流式输出+落日志、嵌入本项目硬纪律(TDD/实时勾选/runbook/隔离审查/合并前停)。当用户想用 headless/无人值守方式跑某份 plan 时调用。"
argument-hint: "<计划文件路径> [merge|no-merge]"
metadata:
  author: "lite-ai-infra"
  related: "scripts/run-plan-headless.sh, ADR-015, ADR-017, constitution §3.4"
---

# headless-plan-runner

把一份实现计划(`docs/superpowers/plans/*.md`)变成一条可在命令行跑的 headless 执行脚本。
底层是可复用的 `scripts/run-plan-headless.sh`;本 skill 负责:确认它在、收集用户输入、给出可直接粘贴的命令 + 监控方式。

## 何时用
用户说"用 headless / claude -p / 无人值守 跑 Plan X""生成执行脚本"等。**不要**用它跑需要中途人工判断的探索性任务(headless 无法纠偏)——那种建议交互模式。

## 步骤(每步用 TodoWrite 跟踪)

1. **确认 runner 在**:`scripts/run-plan-headless.sh` 存在且可执行;不在就从本 skill 的"runner 模板"重新写出并 `chmod +x`。
2. **收集用户输入**(调用时给的 args 优先,缺的才问):
   - 计划文件路径(必填;校验存在)
   - 合并策略:默认 **no-merge(合并前停)**;用户明确要才 `--merge`
   - 分支名(默认 = 计划文件名去 `.md`)
   - 日志路径(默认 `~/.lite-ai-headless/<plan>.<时间>.jsonl`)
3. **给出可执行命令**(填好用户输入),例如:
   ```bash
   cd /Users/yanwen/Documents/github/lite-ai-infra
   scripts/run-plan-headless.sh docs/superpowers/plans/<plan>.md            # 合并前停(默认)
   # 或 scripts/run-plan-headless.sh docs/superpowers/plans/<plan>.md --merge
   ```
4. **给监控方式**:`tail -f <日志路径>`;或 `watch -n5 'git log --oneline -12'`(每 task 一 commit)。
5. **订阅前提提醒**:脚本会 `unset ANTHROPIC_API_KEY`;若仍报 `Credit balance too low`,说明 shell 启动文件(如 `~/.bash_profile`)硬编码了 key 或未登录订阅 → 先注释那行 + `claude` `/login` 选订阅(Pro/Max)。
6. **诚实边界**:headless 跑完不等于完成——按 ADR-017,owner 仍须**手动 spec 完成度检查**;脚本已让 headless 自己跑独立 code review,但人工检查 + 合并默认留给 owner。

## 脚本满足的三条硬需求(对应用户诉求)
1. **订阅模式**:脚本顶部 `unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN`,默认走订阅、不烧 API 余额。
2. **流式 + 日志**:`claude -p --verbose --output-format stream-json ... | tee <log>` —— 控制台实时流 + 全量落 jsonl 日志。
3. **嵌入调用时的用户输入**:计划路径/分支/合并策略/日志路径作为 CLI 参数注入,并写进喂给 `claude -p` 的提示词。

## 提示词里固化的本项目纪律(改纪律时同步改 runner)
- superpowers:executing-plans 逐任务;CLAUDE.md/constitution 全程
- TDD 红→绿;每 task 全绿门禁(pytest/lint-imports/ci_guards/codegen 新鲜度)才进下一 task
- §3.4/ADR-017:每步**实时**勾 `- [x]` + TodoWrite 同步;计划含 runbook(ADR-015)
- 失败走 systematic-debugging,不假绿不跳步
- 完成后 ADR-017 隔离审查:push + 独立 reviewer(requesting-code-review)修 Critical/Important
- 合并策略:默认合并前停等 owner;`--merge` 才自动合并

## runner 模板
若需重建 `scripts/run-plan-headless.sh`,以仓库中该文件的当前内容为准(本 skill 与之配套维护)。
