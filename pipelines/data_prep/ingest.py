# pipelines/data_prep/ingest.py
"""webdataset tar(<key>.jpg + <key>.txt 配对)→ Data-Juicer 多模态 jsonl。
源自 spikes/datajuicer_ray/wds_to_jsonl.py(云上 15,138 条实证),生产化为可 import 函数。"""
from __future__ import annotations

import json
import tarfile
from pathlib import Path

_IMG_EXT = ("jpg", "jpeg", "png", "webp")


def wds_to_jsonl(tar_dir: str, out_dir: str) -> int:
    """解包 tar_dir 下全部 .tar,配对图文写 out_dir/{images/, data.jsonl}。
    孤图(无配对 .txt)丢弃。返回样本数。"""
    out = Path(out_dir)
    img_dir = out / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(out / "data.jsonl", "w") as fh:
        for tar_path in sorted(Path(tar_dir).glob("*.tar")):
            with tarfile.open(tar_path) as tf:
                texts: dict[str, str] = {}
                imgs: dict[str, tuple[tarfile.TarInfo, str]] = {}
                for m in tf.getmembers():
                    if not m.isfile():
                        continue
                    key, _, ext = m.name.rpartition(".")
                    ext = ext.lower()
                    if ext == "txt":
                        texts[key] = tf.extractfile(m).read().decode("utf-8", "ignore").strip()
                    elif ext in _IMG_EXT:
                        imgs[key] = (m, ext)
                for key, (m, ext) in imgs.items():
                    if key not in texts:
                        continue  # 无配对文本的图丢弃
                    p = img_dir / f"{tar_path.stem}_{key.replace('/', '_')}.{ext}"
                    p.write_bytes(tf.extractfile(m).read())
                    fh.write(json.dumps({"text": texts[key], "images": [str(p.resolve())]}) + "\n")
                    n += 1
    return n
