# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""webdataset tar(.tar 内 <key>.jpg + <key>.txt)→ Data-Juicer 多模态 jsonl。

用法:python wds_to_jsonl.py <tar_dir> <out_dir>
产物:<out_dir>/images/*.<ext> + <out_dir>/data.jsonl(每行 {"text":…,"images":[abs_path]})
Spike 2 真跑与后续 pipelines/data_prep 共用此格式(与本地彩排 schema 一致)。
"""
from __future__ import annotations
import json, sys, tarfile
from pathlib import Path

_IMG_EXT = ("jpg", "jpeg", "png", "webp")


def convert(tar_dir: str, out_dir: str) -> int:
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


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: wds_to_jsonl.py <tar_dir> <out_dir>")
    n = convert(sys.argv[1], sys.argv[2])
    print(f"wrote {n} samples → {Path(sys.argv[2]) / 'data.jsonl'}")
