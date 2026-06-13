# /// script
# requires-python = ">=3.12"
# ///
"""扫描 contracts/openapi/*.yaml,生成 Swagger UI 的 URLS(JSON)。
新增契约只需丢进 contracts/openapi/,`make api-docs` 自动纳入下拉——
"一个 Swagger 看全部 API"由此自维护。"""
from __future__ import annotations
import json
import sys
from pathlib import Path


def build_urls(contracts_dir: str = "contracts/openapi") -> list[dict]:
    files = sorted(Path(contracts_dir).glob("*.yaml")) + sorted(Path(contracts_dir).glob("*.yml"))
    return [{"url": f"/contracts/{f.name}", "name": f.stem} for f in files]


if __name__ == "__main__":
    urls = build_urls(sys.argv[1] if len(sys.argv) > 1 else "contracts/openapi")
    print(json.dumps(urls, separators=(",", ":")))
