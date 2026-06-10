#!/usr/bin/env bash
# Spike 2 runner —— Data-Juicer + Ray 在小图文样本上跑清洗（本地彩排）。
#
# 教训(2026-06-10):不能用 `uv run --with ...` 瞬态环境跑 Ray ——
# Ray 会把 driver 的 py_executable(整条 uv run 命令)原样下发给 worker,
# worker 在打包的 working_dir 副本里重新 uv 解析项目环境 → 永久挂死。
# 改用本目录独立持久 venv(仍 uv 管理,不碰主项目 pyproject/.venv)。
set -euo pipefail
cd "$(dirname "$0")/../.."   # repo 根
VENV=spikes/datajuicer_ray/.venv

# 0) 独立 venv(首次自动建;~93 包,无 torch)
if [ ! -x "$VENV/bin/dj-process" ]; then
  uv venv "$VENV" --python 3.12
  VIRTUAL_ENV=$PWD/$VENV uv pip install 'py-data-juicer' 'ray[default]' 'pillow>=10'
fi

# 1) 生成样本（若没生成过）
[ -f spikes/datajuicer_ray/sample/data.jsonl ] || uv run spikes/datajuicer_ray/make_sample.py

# 2) 起本地 Ray head（单机,2 CPU），退出时停掉
"$VENV/bin/ray" start --head --num-cpus 2 --disable-usage-stats
trap '"$VENV/bin/ray" stop >/dev/null 2>&1 || true' EXIT

# 3) 跑 Data-Juicer(HF offline:防 datasets 启动时连外网挂住)
#    先清旧输出:Ray sink 往 cleaned.jsonl/ 目录追加 part 文件,不清会跨运行累计
rm -rf spikes/datajuicer_ray/out/cleaned.jsonl
HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1 \
  "$VENV/bin/dj-process" --config spikes/datajuicer_ray/recipe.yaml

echo "=== 清洗结果 ==="
# Ray data sink 把 cleaned.jsonl 写成目录(内含 part 文件)
cat spikes/datajuicer_ray/out/cleaned.jsonl/*.json* 2>/dev/null | wc -l | xargs echo "留存行数:" \
  || echo "(无输出,检查上面日志)"
