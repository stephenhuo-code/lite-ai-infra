# Spike 2 — Data-Juicer + Ray 多模态清洗

**出口① 硬条件之一。** 本 harness 在本地零成本验证 Data-Juicer + Ray 的图文清洗链路;真判据(100GB + OOM 边界)需上云复跑。

## 跑

```bash
bash spikes/datajuicer_ray/run.sh
```

自动完成:建独立 venv(首次)→ 生成 8 条图文样本(4 好 4 坏)→ 起本地 Ray head → 跑 3 个清洗算子 → 报留存行数(期望 **4**)→ 停 Ray。

## 本地证什么 / 证不了

| 本地能证 | 上云才能证 |
|---|---|
| Data-Juicer + **RayExecutor** 全链路(DAG 调度、算子、导出) | 100GB 规模 |
| 多模态算子有效:text_length / image_shape / aspect_ratio 各滤掉对应坏样本 | **OOM 边界**(出口① 判据) |
| 依赖画像:~93 包、**无 torch**(轻量算子集) | 分片/spill 兜底在集群内存压力下的行为 |

## 本地彩排结果(2026-06-10)

- 8 进 4 出:`bad_empty_text`(空文本)、`bad_long`(5000 字)、`bad_tiny`(2×2)、`bad_ratio`(800×16)全被滤;`good_01..04` 全留 ✓
- 3 算子在 Ray 上 0.45s 完成;输出在 `out/cleaned.jsonl/`(Ray sink 目录式)

## 两个上云前必知的坑(本地彩排换来的)

1. **绝不能用 `uv run --with ...` 瞬态环境跑 Ray。** Ray 会把 driver 的 py_executable(整条 uv run 命令)下发给 worker,worker 在打包的 working_dir 副本里重新 uv 解析环境 → **永久挂死**(本地实测挂 1.5h 无进展)。必须用持久 venv / 容器镜像。K8s(KubeRay)天然是镜像方式,无此问题,但**自定义镜像里要装齐 data-juicer 依赖**。
2. **`HF_HUB_OFFLINE=1`**:datasets/HF hub 启动时会尝试连外网,网络不通/走代理时静默挂起。离线集群(阿里云 VPC 内)务必设置;需要 HF 资源的算子提前把模型烤进镜像。

## recipe 说明

`recipe.yaml` 只选了**无需下载模型**的轻量算子,本地秒跑。上云跑 100GB 时按真实清洗需求换算子(去重 / CLIP 相似度等),那时才会引入 torch 等重依赖——届时评估 OOM 边界正是 spike 目的。
