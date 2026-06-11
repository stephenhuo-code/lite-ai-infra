# 数据 Spike 1 结论 —— Lance on 真阿里云 OSS(2026-06-12)

**判定:GO(带 3 条工程约束)。** 环境:ECS e-c1m4.large(2C8G,cn-hangzhou-k)→ OSS(同 region);合成向量 dim=768;STS 实例角色凭据。

## 延迟数据

| endpoint | rows(vec 体积) | write | scan(full) | scan(proj=id) | random_take |
|---|---|---|---|---|---|
| **内网** | 100k(307MB) | 164 MB/s | **212 MB/s** | 0.019s | 0.276 ms/row |
| **内网** | 200k(614MB) | 179 MB/s | 201 MB/s | 0.025s | 0.341 ms/row |
| **内网** | 500k(1.5GB) | 193 MB/s | 98 MB/s* | 0.047s | 0.310 ms/row |
| 公网对照 | 200k(614MB) | 13 MB/s | 10 MB/s | 0.032s | 0.388 ms/row |

\* 500k 全扫降速疑似 2C8G 实例内存压力(1.5GB 表整表读入),非 OSS 瓶颈;列裁剪/随机访问不受影响。

**对照预设判定标准(plan Task 5):内网顺序扫 ≥80MB/s ✓(98–212)、随机 ≤2ms/row ✓(0.28–0.39)→ PASS,无需 JindoFS 降级。**

## 三条工程约束(实测踩出,均已修进 harness/库)

1. **写提交需 `commit_lock`**:OSS 不支持 `If-None-Match` 条件写(`NotImplemented`),Lance 默认 manifest 提交失败;`conditional_put=disabled` 也不行(object_store 拒 Create 模式)。**解法 = lance `commit_lock` 外部锁口子**(单写者 no-op 锁安全)。**多写者并发提交需真锁(如基于 OSS x-oss-forbid-overwrite 或外部锁服务)→ 记 vN+/S2a 课题。**
2. **必须内网 endpoint**(`-internal`):公网慢 15–20 倍且计流量费。
3. **virtual-hosted + bucket 拼进 endpoint**:OSS 拒 path-style;而 lance/object_store 在 virtual-hosted 模式下要求 endpoint 自带 bucket 域名,否则 list 打到根域 403。

## 边界声明

按 owner 决策(2026-06-11)数据规模降为 1GB 档:本结论覆盖**延迟/吞吐特征与兼容性**;**100GB+ 持续吞吐与 DataLoader 饱和验证移交 S2a**(10TB 放大阶段),按 ADR-014 门禁关闭记录之。

复跑:`spikes/lance_oss/bench.py`,env 见文件头(OSS_COMMIT_MODE=lock + 内网 endpoint)。
