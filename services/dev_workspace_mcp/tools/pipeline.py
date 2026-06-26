# services/dev_workspace_mcp/tools/pipeline.py
# DJ recipe 脚手架 + 运行命令。DJ/Python 执行在 omnigent 沙箱(agent 跑命令),本工具只生成
# 模板到工作目录 + 返回标准运行命令(复用 pipelines/data_prep 的 DJ 约定)。
from __future__ import annotations

import json


def scaffold_dj_recipe(*, dataset: str, export: str, ops: list[dict], np: int = 4) -> str:
    lines = [f'dataset_path: "{dataset}"', f'export_path: "{export}"', f"np: {np}", "process:"]
    for op in ops:
        (name, params), = op.items()
        lines.append(f"  - {name}:")
        for k, v in params.items():
            lines.append(f"      {k}: {json.dumps(v)}")
    return "\n".join(lines) + "\n"


def dj_run_command(*, recipe_path: str) -> str:
    return f"dj-process --config {recipe_path}"
