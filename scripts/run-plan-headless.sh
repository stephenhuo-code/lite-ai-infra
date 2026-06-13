#!/usr/bin/env bash
# headless 执行一个实现计划(由 skill `headless-plan-runner` 生成/维护)。
# 用法:
#   scripts/run-plan-headless.sh <plan.md> [--branch NAME] [--merge] [--log PATH]
# 默认:分支 = plan 文件名;合并前停下(--merge 才自动合并);日志流式写入 ~/.lite-ai-headless/。
set -euo pipefail

PLAN="${1:?usage: run-plan-headless.sh <plan-file> [--branch NAME] [--merge] [--log PATH]}"; shift || true
[ -f "$PLAN" ] || { echo "plan 文件不存在: $PLAN" >&2; exit 1; }
BRANCH=""; MERGE=0; LOG=""
while [ $# -gt 0 ]; do case "$1" in
  --branch) BRANCH="${2:?}"; shift 2;;
  --merge)  MERGE=1; shift;;
  --no-merge) MERGE=0; shift;;
  --log)    LOG="${2:?}"; shift 2;;
  *) echo "未知参数: $1" >&2; exit 1;;
esac; done
BRANCH="${BRANCH:-$(basename "$PLAN" .md)}"
LOG="${LOG:-$HOME/.lite-ai-headless/$(basename "$PLAN" .md).$(date +%Y%m%d-%H%M%S).jsonl}"
mkdir -p "$(dirname "$LOG")"
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"; cd "$ROOT"

# 1) 订阅模式:清掉 API key(否则走 API 计费,余额不足会报 "Credit balance too low")
unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN
if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  echo "⚠️  ANTHROPIC_API_KEY 仍被设置(可能在 shell 启动文件硬编码)。请注释掉再跑,否则不会走订阅。" >&2
fi
echo "✅ API key 已 unset → 订阅模式。若报 credit/login 问题:先 \`claude\` → /login 选订阅(Pro/Max)。"

# 2) 合并策略(ADR-017:owner 的 spec 完成度人工检查 + 合并默认留给人)
if [ "$MERGE" = 1 ]; then
  MERGE_POLICY="CI 绿后可自动合并 main 并删分支。"
else
  MERGE_POLICY="**合并 main 之前停下**:push 分支 + 输出完成总结,等 owner 确认;不要自动合并、不要推 main。"
fi

# 3) 提示词(嵌入计划路径 + 本项目硬纪律)
read -r -d '' PROMPT <<EOF || true
用 superpowers 执行实现计划:${PLAN}
先调用 superpowers:executing-plans,严格按计划的 checkbox 逐任务实现。
全程遵守仓库 CLAUDE.md / docs/constitution.md:API 优先、TDD(红→绿)、证据先于断言;
§3.4 计划纪律——每完成一步**实时**勾 [x] + TodoWrite 同步 in_progress/completed(ADR-017);
计划含手动验收 runbook(ADR-015)。

【自主执行】已获全部授权:任务之间不要停、不要征求许可,一口气到底。在分支 ${BRANCH} 上做
(不存在则从当前分支创建)。每个 task 走 TDD、跑通即 git commit。每 task 结束保证全绿:
\`uv run pytest -q\` 全绿、\`uv run lint-imports\` 0 broken、\`bash scripts/ci_guards.sh\` exit 0、
涉及契约跑 \`make gen\` 且 git diff 无残留。失败先 superpowers:systematic-debugging 定位根因,
不假绿、不跳步。

【完成后:ADR-017 隔离审查】全部绿 → push 分支 → 用 superpowers:requesting-code-review 派
**独立 reviewer** 审 main..HEAD,Critical/Important 当场修到绿。然后:${MERGE_POLICY}
注意:spec 完成度的**人工**检查由 owner 做,headless 不替代(机器自评不算数)。

【完成时输出】逐 task 绿色证据 + 全量(单元+集成)结果 + commit 列表 + reviewer 结论 + 待办(合并)。
EOF

echo "plan=$PLAN  branch=$BRANCH  merge=$MERGE"
echo "日志(流式 jsonl)→ $LOG    另开终端可: tail -f \"$LOG\""
echo "──────────── headless 开始 ────────────"
# 流式输出到控制台 + 落盘(stream-json:每步思考/工具/结果都可见)
claude -p --dangerously-skip-permissions --verbose --output-format stream-json "$PROMPT" 2>&1 | tee "$LOG"
echo "──────────── headless 结束 ────────────  日志: $LOG"
