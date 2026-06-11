# 数据 Spike 2 结论 —— Data-Juicer + Ray on 阿里云(2026-06-12)

**判定:GO(管线机制级;规模边界按 ADR-014 移交 S2a)。**
环境:ECS e-c1m4.large(2C8G,另驻 Keycloak+PG ~2GB);数据:CC3M 3 shards → **15,138 条真实图文**(`wds_to_jsonl.py` 转换);Ray 2.55.1 单机,3 个轻算子(text_length / image_shape / aspect_ratio)。

## np 递增实测

| np | 耗时 | 内存峰值 | 输出行 | 备注 |
|---|---|---|---|---|
| 2 | 70s | 3270MB | 15138 | 基线;≈216 样本/s |
| 3 | 55s | 3284MB | 15138 | 提速 21%(2C 上超额并发仍有收益,IO 等待重叠) |
| 4 | 56s | 3297MB | 15138 | 增益封顶(CPU 饱和) |

- **无 OOM、无 worker kill**;Ray 日志有 spill 活动痕迹,对象溢写机制在位
- **内存对 np 几乎平坦**(+14MB/np):轻算子下基线开销(Ray object store + datasets)主导,单 worker 增量极小
- 吞吐参考:~1.4GB / 70s ≈ **20MB/s per 2C 经济实例**(线性外推 8C ≈ 80MB/s,待 S2a 实证)

## 如实声明(边界)

1. **真实 OOM 边界未触及**:1GB + 轻算子在 8GB 机上峰值仅 3.3GB。重算子(CLIP 过滤/去重 embedding)与 100GB+ 规模的内存边界 → **S2a 实测**(ADR-014 门禁关闭记录在案)。
2. **零过滤是数据特性而非算子失效**:CC3M 为预清洗数据集,3 个轻过滤全通过;算子有效性已由本地彩排证明(8 进 4 出,脏样本全滤,见 `README.md`)。
3. 上云期间另复用了本地彩排的两条教训(uv 瞬态环境禁用于 Ray、HF offline),零复发。

## 给 Plan 2(pipelines/data_prep)的参数建议

- 单机 Ray:np = vCPU 数 +1(IO 重叠收益)起步;轻算子内存按"基线 3GB + 50MB/np"预算
- 重算子引入时:先 1 shard 标定单样本内存斜率,再定分片大小;Ray spill 兜底已验在位
- 数据进出:webdataset tar → `wds_to_jsonl.py` → DJ;输出目录式 jsonl(Ray sink),下游按目录读

复跑:`/tmp/spike2.sh` 模式(见 git 历史)或本地 `spikes/datajuicer_ray/run.sh`。
