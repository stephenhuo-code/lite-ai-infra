---
name: headless-plan-runner
description: 当用户想用 headless / 无人值守方式(codex -p)执行一份实现计划时使用——例如"用 headless 跑这个计划""生成 codex -p 脚本""后台执行计划""跑这个计划不用盯着"。通用,不限本项目。
---

# headless-plan-runner(headless 计划执行器)

## 概述
把任意仓库的一份实现计划(markdown)用 `codex -p` 无人值守地端到端跑完。包装同目录的 `run-plan-headless.sh`:输出**流式到控制台 + 落日志文件**、喂给 `codex -p` 的提示词把项目细节全部交给该仓库自己的 `AGENTS.md`。与具体项目解耦。

## 何时用
- 用户要无人值守地跑一份计划,或要一个 `codex -p` 运行脚本。

**何时不要用**:需要中途人工判断的探索性工作——headless 无法纠偏,这种建议用交互模式。

## 速查
```bash
.agents/skills/headless-plan-runner/run-plan-headless.sh <plan.md>            # 合并前停(默认)
.agents/skills/headless-plan-runner/run-plan-headless.sh <plan.md> --merge    # 绿了自动合并
.agents/skills/headless-plan-runner/run-plan-headless.sh <plan.md> --branch X --log /tmp/x.jsonl
tail -f ~/.headless-plans/<plan>.<时间戳>.jsonl     # 另开终端看实时日志
```
在 plan 所在的 git 仓库里执行;分支默认 = plan 文件名。

## 脚本保证的三件事(对应诉求)
1. **Codex CLI** —— 使用本机 `codex -p`,不再调用 `claude -p`。
2. **流式 + 日志** —— `codex -p … | tee <log>`:控制台实时 + 全量日志。
3. **调用时的用户输入** —— plan 路径 / 分支 / 合并策略 / 日志路径作 CLI 参数,注入到 `codex -p` 提示词。

## 调用本 skill 时怎么做
1. 拿到计划文件路径(及合并策略,默认=合并前停),校验存在。
2. 确认 `run-plan-headless.sh` 存在且可执行;缺了就从本目录重建。
3. 打印填好用户输入的可直接运行命令 + `tail -f` 监控行。
4. 若 `codex` 命令不存在或未登录,提示用户先安装/登录 Codex CLI。

## 提示词固化的通用纪律(不绑项目)
- superpowers:executing-plans,按计划 checkbox 逐任务
- **遵守该仓库自己的 AGENTS.md** 来发现测试/lint/构建的"全绿"门禁(不硬编码命令)
- TDD(红→绿);每步实时勾选 + TodoWrite 同步状态
- 失败走 superpowers:systematic-debugging;不假绿、不跳步
- 全绿后:push + 独立 superpowers:requesting-code-review,修 Critical/Important
- 合并策略按 `--merge`;最终 spec 验收的人工检查留给 owner

## 常见错误
- 拿 headless 跑探索性工作 → 它问不了你,改用交互。
- 本机没有 `codex` 命令或未登录 → 先安装/登录 Codex CLI。
- 指望脚本知道项目测试命令 → 它有意交给该仓库的 AGENTS.md。
