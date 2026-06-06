# ADR-009: 训练调度器选型 — Volcano + torchrun（v1/v2），Ray Train 不采用

- 状态：Accepted
- 日期：2026-05-12
- 决策人：平台团队（P1/P2/P3）
- 相关：design doc §1.2 子系统分解 / §2.4 v1→v2 演进点 / §3.1 完整组件清单 / ADR-008（数据集元数据权威）

---

## Context

### 问题来源

平台数据管线已经引入 KubeRay（Ray Data + Data-Juicer），Ray 基础设施已在栈内。自然引出一个问题：训练调度是否也应该统一用 Ray Train，从而以 KubeRay 作为唯一的 workload operator，替代 Volcano？

候选方案：

| 方案 | 训练 operator | 数据 operator | 调度统一性 |
|---|---|---|---|
| **A：Volcano + torchrun** | Volcano（VolcanoJob） | KubeRay（RayCluster） | 两种 operator |
| **B：Ray Train** | KubeRay（RayJob） | KubeRay（RayCluster） | 一种 operator |

### 两方案核心差异

#### 调度模型

| 维度 | Volcano | Ray Train |
|---|---|---|
| Gang scheduling 层次 | K8s Pod 层（精确控制） | Ray actor 层（Ray 内部管） |
| 所有 worker 同时起 | 由 Volcano PodGroup 保证 | 由 RayCluster 自身保证 |
| 弹性训练（节点故障不重启整组） | ❌ 全组重启 | ✅ Ray actor supervision |
| 训练代码模型 | torchrun 脚本（标准入口） | `TorchTrainer(train_func)` 函数式 |

#### 框架兼容性

| 框架 | Volcano + torchrun | Ray Train |
|---|---|---|
| PyTorch DDP | ✅ 天然 | ✅ TorchTrainer |
| DeepSpeed | ✅ 天然 | ✅ DeepSpeed backend |
| FSDP（多机） | ✅ torchrun 多机 | ✅ FSDP backend |
| **Megatron-LM** | ✅ **天然**（torchrun 是标准启动方式） | ⚠️ **非标准路径，无成熟社区实践** |

#### Kueue 集成

两方案均有 Kueue 原生集成：Kueue 支持 VolcanoJob 和 RayJob 两种 workload 类型，per-tenant LocalQueue 对两者都有效。Kueue 不是本次决策的差异点。

### 关键约束：Megatron 是 v2 硬需求

v2 训练目标为超过 1B 参数规模的大模型，需要 Megatron-LM 的 3D 并行（Tensor Parallel + Pipeline Parallel + Data Parallel）。

Megatron-LM 的架构约束：

1. **进程启动模型**：Megatron 通过 `torchrun`（或 `torch.distributed.launch`）启动，每个 rank 是一个独立进程，通过 NCCL 通信。这是 Megatron 的基本假设，不是可以绕过的配置项。

2. **Ray Train 兼容性**：Ray Train 的 `TorchTrainer` 将训练逻辑封装为 Ray actor，与 Megatron 的进程模型存在根本冲突。社区没有 Ray Train + Megatron 的成熟实践路径；现有尝试均需要对 Megatron 核心代码做非标准改动。

3. **eRDMA / NCCL 调优**：多机 Megatron 训练依赖底层 RDMA 网络（阿里云 eRDMA），调优路径建立在 torchrun + NCCL 基础上，与 Ray 的网络层无关。

**如果选 Ray Train**：v2 引入 Megatron 时必须引回 Volcano，等于在 v1→v2 之间多一次调度器切换，且 X-user team 的训练代码需要从 `train_func` 模型回退到 torchrun 脚本。

---

## Decision

**选方案 A：Volcano + torchrun，v1 和 v2 保持一致。Ray Train 不用于训练调度。**

KubeRay 继续用于**数据管线**，但范围**严格收窄到 Data-Juicer 一类工作负载**（详见 platform-design.md §3.7.1），**不扩展到训练 workload，也不扩散到 embedding / 通用 ETL / 评估等其它批处理**——后者一律走 Argo + 普通 K8s Job。

两者职责彻底分离，且数据侧 Ray 范围被锁死：

```
Data-Juicer 清洗  →  KubeRay  (RayCluster，由 Argo Workflow 拉起和回收；autoscaler 关闭)
其它数据批处理     →  Argo + K8s Job  (embedding 批量、Lance 重打包、ETL、评估)
训练/SFT          →  Volcano  (VolcanoJob，torchrun 多进程 DDP/DeepSpeed/Megatron)
配额管理          →  Kueue    (统一管理以上 workload，per-tenant LocalQueue)
```

**新增 Ray 用例必须走 ADR 评审**，并证明"Argo + K8s Job 不足以满足"。这条契约由 PR review 把关（引入新 `RayCluster`/`RayJob` 必须附 ADR 引用）。

### 训练镜像契约因此锁定为 torchrun 模型

```
契约入口：/opt/train/entrypoint.sh
启动方式（单机和多机统一）：
    torchrun \
      --nnodes=$NNODES \
      --node_rank=$NODE_RANK \
      --nproc_per_node=$NPROC_PER_NODE \
      --master_addr=$MASTER_ADDR \
      --master_port=$MASTER_PORT \
      train.py

必接环境变量（由 Volcano + 平台注入，单机/多机均同一套语义）：
    # —— 分布式拓扑（torchrun 直接消费）——
    NNODES            节点总数（= VolcanoJob 的 worker replicas）
    NODE_RANK         当前节点序号，0..NNODES-1（来自 Volcano pod index）
    NPROC_PER_NODE    每节点本地进程数（通常 = 本节点 GPU 数）
    MASTER_ADDR       rank-0 节点地址（Volcano PodGroup headless service）
    MASTER_PORT       rendezvous 端口

    # —— 派生/全局元数据（供 train.py 自身使用，不传给 torchrun）——
    WORLD_SIZE        全局总 rank 数 = NNODES * NPROC_PER_NODE
    RANK              全局 rank（torchrun 自动注入到子进程，entrypoint 不必显式设置）

    # —— 业务变量 ——
    DATA_URI / OUTPUT_URI / MLFLOW_TRACKING_URI / MLFLOW_RUN_ID
    CKPT_URI / TENANT_ID

必接信号：SIGTERM → 优雅保存 checkpoint
```

> ⚠️ **不要写 `--nproc_per_node=$WORLD_SIZE`**：`WORLD_SIZE` 是跨所有节点的全局 rank 数，`--nproc_per_node` 是单节点本地进程数。两者仅在 `NNODES=1` 时偶然相等；多机场景下会让每个节点都拉起 `WORLD_SIZE` 个进程，rendezvous 与 NCCL 拓扑直接崩溃。

v2 Megatron 镜像遵循同一契约，`entrypoint.sh` 内部换成 Megatron 的 torchrun 启动命令（3D 并行的 TP/PP/DP 拆分通过 `train.py` 内部参数表达，不影响 torchrun 五元组）。**平台调度层（Volcano + Kueue）零改动**——只需把 v1 已暴露的拓扑五元组延伸到多 worker replica 即可，Volcano PodGroup 原生提供。这是"镜像契约"设计的核心价值：框架升级不影响平台。

---

## Consequence

### 正面

- **v1/v2 调度层一致**：Volcano 不是 v1 的临时组件，而是永久组件，避免 v2 引入 Megatron 时的调度器切换成本
- **Megatron 兼容有保证**：torchrun 脚本模型与 Megatron 天然兼容，3D 并行配置通过环境变量传入，不需要改 Megatron 核心代码
- **训练代码 portable**：torchrun 脚本在任何标准 GPU 环境都能运行（本地、staging、prod），不绑定 Ray 运行时
- **Gang scheduling 精确**：Volcano PodGroup 在 K8s Pod 层保证"所有 worker 同时起或全不起"，比 Ray actor 层的协调更直接，GPU 资源浪费窗口更小
- **调试路径清晰**：训练进程即 K8s Pod，`kubectl logs` / `kubectl exec` 直接排查；不需要理解 Ray actor 模型

### 负面

- **两种 operator 共存**：KubeRay + Volcano，运维需要熟悉两套 CRD 和控制器。相比 Ray Train 方案多维护一个 operator。
- **无弹性训练**：Volcano 采用 gang restart（节点故障时整组重启续最新 checkpoint），不支持节点故障后动态缩减 world_size 继续训练。v1 验收标准是"丢失 ≤1 小时进度"，gang restart 能满足；v2 超大规模训练时如需弹性，需单独评估。
- **checkpoint 逻辑自担**：Ray Train 内置 checkpoint 续训钩子；Volcano 方案需要自行实现 SIGTERM → 保存 → 重启 → 加载的完整逻辑（已在 design doc §6.3 容错设计中覆盖）。

### 中性

- Kueue 对 VolcanoJob 和 RayJob 的配额管理语义完全等价，per-tenant LocalQueue 配置不因此次决策有任何变化
- v2 如需弹性训练（节点故障不重启整组），在 Volcano 框架内可通过 Volcano 的 Elastic Job 特性扩展，不必切换到 Ray Train

---

## 实施约束

1. **Ray 仅用于数据管线**：任何训练 workload（预训练 / SFT / embedding 批处理中的训练部分）必须走 Volcano Job，禁止在训练路径中创建 RayJob
2. **训练镜像契约不可引入 Ray 依赖**：`train-pytorch-ddp` / `train-deepspeed` 镜像不安装 Ray；镜像内通过 torchrun 启动，不通过 `ray.init()`
3. **v2 Megatron 镜像遵循同一契约**：entrypoint.sh 接口不变，内部启动命令替换为 Megatron 的 `pretrain_*.py`
4. **CI 检查**：训练镜像构建流水线中，grep 检查镜像内是否意外安装了 `ray` package

---

## 后续动作

- [ ] Sprint 1：P1 实现 Volcano Job 模板（含 PodGroup gang scheduling 配置 + torchrun 入口）
- [ ] Sprint 1：P1 验证 8 GPU DDP + Volcano + Kueue LocalQueue 全链路（mini model）
- [ ] Sprint 5 末（v2 规划时）：确认 Megatron 版本 + 多机 eRDMA 网络要求，评估 Volcano Elastic Job 是否需要启用
