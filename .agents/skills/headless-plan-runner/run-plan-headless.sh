#!/usr/bin/env bash
# 通用:headless 执行任意仓库的一份实现计划(codex -p)。与 SKILL.md 同目录。
# 用法:
#   run-plan-headless.sh <plan-file> [--branch NAME] [--merge] [--log PATH]
# 默认:在 plan 所在仓库执行;分支 = plan 文件名;合并前停(--merge 才自动合并);
#       日志流式落 ~/.headless-plans/。不绑定任何特定项目——纪律来自该仓库自己的 AGENTS.md。
set -euo pipefail

PLAN="${1:?usage: run-plan-headless.sh <plan-file> [--branch NAME] [--merge] [--log PATH]}"; shift || true
[ -f "$PLAN" ] || { echo "plan 文件不存在: $PLAN" >&2; exit 1; }
PLAN="$(cd "$(dirname "$PLAN")" && pwd)/$(basename "$PLAN")"   # 绝对路径
BRANCH=""; MERGE=0; LOG=""
while [ $# -gt 0 ]; do case "$1" in
  --branch) BRANCH="${2:?}"; shift 2;;
  --merge)  MERGE=1; shift;;
  --no-merge) MERGE=0; shift;;
  --log)    LOG="${2:?}"; shift 2;;
  *) echo "未知参数: $1" >&2; exit 1;;
esac; done
STEM="$(basename "$PLAN" .md)"
BRANCH="${BRANCH:-$STEM}"
LOG="${LOG:-$HOME/.headless-plans/$STEM.$(date +%Y%m%d-%H%M%S).jsonl}"
mkdir -p "$(dirname "$LOG")"
ROOT="$(cd "$(dirname "$PLAN")" && (git rev-parse --show-toplevel 2>/dev/null || pwd))"; cd "$ROOT"

# 1) Codex CLI 可用性
command -v codex >/dev/null 2>&1 || { echo "找不到 codex 命令:请先安装/登录 Codex CLI。" >&2; exit 1; }

# 2) 合并策略(默认:把最终验收与合并留给人)
if [ "$MERGE" = 1 ]; then
  MERGE_POLICY="CI 绿后可自动合并 main 并删分支。"
else
  MERGE_POLICY="**合并 main 之前停下**:push 分支 + 输出完成总结,等人确认;不要自动合并、不要推 main。"
fi

# 3) 提示词(纪律来自该仓库自己的 AGENTS.md;本脚本只固化通用执行规范)
read -r -d '' PROMPT <<EOF || true
用 superpowers 执行实现计划:${PLAN}
先调用 superpowers:executing-plans,严格按计划的 checkbox 逐任务实现。
**全程遵守本仓库根的 AGENTS.md 及其引用的约定**(测试/lint/构建命令、目录纪律、提交规范等)——
不要假设具体命令,从 AGENTS.md / Makefile / 配置里发现该项目的"全绿"门禁。

【自主执行】已获全部授权:任务之间不停、不征求许可,一口气到底。在分支 ${BRANCH} 上做
(不存在则从当前分支创建)。每个 task 走 TDD(先写测试跑红 → 实现跑绿)、跑通即 git commit。
每完成一步**实时**勾 [x] + TodoWrite 同步 in_progress/completed(进度随时可见、可中断可续)。
每 task 结束必须跑通该项目的测试/lint/构建门禁(全绿)才进下一 task;失败先
superpowers:systematic-debugging 定位根因再改,不假绿、不跳步。

【完成后:隔离审查】全部绿 → push 分支 → 用 superpowers:requesting-code-review 派
**独立 reviewer** 审 main..HEAD,Critical/Important 当场修到绿。然后:${MERGE_POLICY}
注意:最终的 spec 完成度/验收**人工**检查留给 owner,headless 不替代(机器自评不算数)。

【完成时输出】逐 task 绿色证据 + 全量测试结果 + commit 列表 + reviewer 结论 + 待办(合并)。
EOF

echo "plan=$PLAN  repo=$ROOT  branch=$BRANCH  merge=$MERGE"
echo "日志(流式 jsonl)→ $LOG    另开终端: tail -f \"$LOG\""
echo "──────────── headless 开始 ────────────"
codex -p "$PROMPT" 2>&1 | tee "$LOG"
echo "──────────── headless 结束 ────────────  日志: $LOG"
