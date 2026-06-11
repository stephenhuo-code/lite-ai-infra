# pipelines/data_prep/recipe.py
from __future__ import annotations

import yaml

# Spike 2 实证的轻算子默认集(spikes/datajuicer_ray/RESULTS-aliyun.md)
_DEFAULT_PROCESS = [
    {"text_length_filter": {"min_len": 3, "max_len": 2000}},
    {"image_shape_filter": {"min_width": 8, "min_height": 8}},
    {"image_aspect_ratio_filter": {"min_ratio": 0.2, "max_ratio": 5.0}},
]

def build_recipe(input_jsonl: str, out_dir: str, np: int,
                 process: list[dict] | None = None, project: str = "data-prep") -> str:
    """生成 Data-Juicer RayExecutor recipe(np 取 vCPU+1 起步,Spike 2 结论)。"""
    cfg = {
        "project_name": project,
        "dataset_path": input_jsonl,
        "export_path": f"{out_dir}/cleaned.jsonl",
        "executor_type": "ray",
        "ray_address": "auto",
        "np": np,
        "text_keys": "text",
        "image_key": "images",
        "process": process if process is not None else _DEFAULT_PROCESS,
    }
    return yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False)
