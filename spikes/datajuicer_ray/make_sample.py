# /// script
# requires-python = ">=3.12"
# dependencies = ["pillow>=10", "numpy>=2"]
# ///
"""
生成一个**小图文多模态样本**给 Data-Juicer + Ray 清洗(Spike 2 本地彩排用)。
故意混入几条"脏"样本(空文本 / 极小图 / 极端宽高比),好让清洗算子有东西可过滤。
产物:sample/images/*.png + sample/data.jsonl(Data-Juicer 多模态格式)。
"""
from __future__ import annotations
import json, os
from pathlib import Path
import numpy as np
from PIL import Image

HERE = Path(__file__).parent
IMG_DIR = HERE / "sample" / "images"
JSONL = HERE / "sample" / "data.jsonl"


def _img(path: Path, w: int, h: int):
    rng = np.random.default_rng(abs(hash(path.name)) % (2**32))
    arr = rng.integers(0, 256, size=(h, w, 3), dtype=np.uint8)
    Image.fromarray(arr, "RGB").save(path)


def main():
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    # (文件名, 宽, 高, 文本) —— 好/坏混合
    specs = [
        ("good_01.png", 256, 256, "a red square on a textured background"),
        ("good_02.png", 320, 240, "landscape photo of synthetic noise pattern"),
        ("good_03.png", 200, 200, "abstract multicolor pixel grid for testing"),
        ("good_04.png", 512, 384, "wide synthetic image with random rgb pixels"),
        ("bad_tiny.png", 2, 2, "this image is too tiny and should be filtered"),
        ("bad_ratio.png", 800, 16, "extreme aspect ratio banner image"),
        ("bad_empty_text.png", 256, 256, ""),
        ("bad_long.png", 256, 256, "x" * 5000),
    ]
    rows = []
    for name, w, h, text in specs:
        p = IMG_DIR / name
        _img(p, w, h)
        rows.append({"text": text, "images": [str(p.resolve())]})

    JSONL.parent.mkdir(parents=True, exist_ok=True)
    with open(JSONL, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print(f"wrote {len(rows)} samples → {JSONL}")
    print(f"images → {IMG_DIR}")


if __name__ == "__main__":
    main()
