# Spike 1 — Lance on 对象存储（读写延迟）

**出口① 硬条件之一。** 本 harness 在本地零成本验证 Lance 的对象存储读写路径,并产出基线延迟;真判据需上云复跑。

## 跑

```bash
# 本地 MinIO 基线（需先 `make dev-up`）
uv run spikes/lance_oss/bench.py

# 上云复跑（同一脚本零改,只改 env）
OSS_ENDPOINT=https://oss-cn-hangzhou.aliyuncs.com \
OSS_ACCESS_KEY=<AK> OSS_SECRET_KEY=<SK> OSS_REGION=cn-hangzhou \
SPIKE_BUCKET=<bucket> SPIKE_ROWS=2000000 SPIKE_DIM=768 \
  uv run spikes/lance_oss/bench.py
```

调规模:`SPIKE_ROWS`(默认 20000)、`SPIKE_DIM`(默认 256)、`SPIKE_TAKE_N`(随机访问行数,默认 1000)。

## 本地证什么 / 证不了

| 本地能证(MinIO) | 上云才能证(真 OSS) |
|---|---|
| Lance 写/全扫/**列裁剪**/随机访问 API 全通 | 真 OSS 跨网延迟(spike 核心问题) |
| S3 兼容 + path-style 路径正确 | 100GB 规模能否喂饱训练 DataLoader |
| **本地基线延迟**(下限参考) | JindoFS/本地缓存的**降级结论** |

## 本地基线参考（2026-06-09，MinIO，rows=20000 dim=256 ≈20.5MB）

| op | seconds | 说明 |
|---|---|---|
| write | 0.505 | 40.5 MB/s |
| scan(full) | 0.089 | 230 MB/s,全列 |
| scan(proj=id) | 0.004 | 列裁剪,显著快于全扫 → Lance 列存优势成立 |
| random_take ×1000 | 0.089 | 0.089 ms/row |

> 这是**局域网下限**。上云后把数字填进出口① 结论表,给 go/降级判断。
