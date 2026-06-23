#!/usr/bin/env python3
"""取 coco-30-val ~64 条 → 打包 webdataset tar({key}.jpg+{key}.txt)。e2e 夹具(runbook 用)。"""
import io, os, tarfile
from datasets import load_dataset

N = int(os.getenv("N", "64"))
out_dir = os.getenv("OUT", "./.smoke")
os.makedirs(out_dir, exist_ok=True)
ds = load_dataset("sayakpaul/coco-30-val-2014", split="train", streaming=True)
tar_path = os.path.join(out_dir, "coco-smoke.tar")
with tarfile.open(tar_path, "w") as tar:
    for i, row in zip(range(N), ds):
        key = f"{i:05d}"
        img = row.get("image") or row.get("Image")
        cap = (row.get("caption") or row.get("Caption") or "").strip()
        if img is None or not cap:
            continue
        buf = io.BytesIO(); img.convert("RGB").save(buf, format="JPEG"); b = buf.getvalue()
        ti = tarfile.TarInfo(f"{key}.jpg"); ti.size = len(b); tar.addfile(ti, io.BytesIO(b))
        cb = cap.encode("utf-8"); tt = tarfile.TarInfo(f"{key}.txt"); tt.size = len(cb); tar.addfile(tt, io.BytesIO(cb))
print("wrote", tar_path)
