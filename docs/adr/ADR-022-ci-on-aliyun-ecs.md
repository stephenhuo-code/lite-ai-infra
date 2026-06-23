# ADR-022: CI 环境 = 整套阿里云 ECS

- 状态:**Proposed（2026-06-23,待 owner 拍板）**
- 决策人:owner
- 相关:宪法 §3(地基/争议落 ADR)/ §7(扩范围走 ADR)/ §5.2(密钥)/ §5.3(环境对等);ADR-020(上传 presigned;真 OSS parity——virtual-hosted/CORS/multipart ETag,MinIO 测不出)/ ADR-021(配置体系,`configs/test.yaml` 是本 ADR 输入);现有 `deploy/test/`(Keycloak+Postgres compose + Terraform OSS+RAM+STS 雏形)、`.github/workflows/ci.yml`、`tests/conftest.py:_reachable`

---

## Context
owner 决定 **CI 环境整套跑阿里云 ECS**(不是仅把存储换 OSS)。动因:ADR-020 登记的 **prod parity 复验**(virtual-hosted presigned / multipart ETag / OSS CORS)本地 MinIO 覆盖不到,需在真阿里云上验;且终态 staging/prod 在阿里云,CI 贴近真环境降低"dev 测得过 prod 挂"的风险(§5.3)。这是把 CI 的信任根从"GitHub runner 上临时 compose"迁到**常驻云基础设施**——地基级、有争议、部分不可逆,故落 ADR。现有 `deploy/test/`(Terraform OSS+RAM+STS、Postgres+Keycloak compose)是雏形,缺 VPC/SG/ECS/RDS。

## Decision(待 owner 逐条拍板)

1. **部署形态 = compose-on-ECS**(推荐):单台/少量 ECS 上 `docker compose` 起全栈(Keycloak+Gravitino+4 服务镜像;OSS 用真阿里云不进 compose)。复用现有 compose 资产,跳跃最小。**ACK(K8s)留 S2c**(spec/ops runbook 本就把集群推后)。
   - 候选否决:现在上 ACK —— 过早,超当前轮人力。

2. **CI↔ECS 连接 = GitHub Actions SSH 部署**:CI job 经 SSH(key 走 Actions secret)连 ECS → `git pull`/拉镜像 → `docker compose up -d` → 等健康 → 跑集成 → 清理。凭据流先用 **Actions secret**;**OIDC→RAM 联合**留强化项。

3. **CI 隔离与清理**:用**独立 CI OSS 桶**(非个人 `hyw2026` 桶)+ `ci-<run-id>/` 前缀隔离并发 + bucket **lifecycle 规则 / 跑后显式删**(不静默堆垃圾,§3 不静默砍范围反向——不静默留垃圾)。

4. **Keycloak 后端 = RDS PostgreSQL**(prod 级持久);替代 test compose 的容器 Postgres。

5. **服务镜像**:为 4 个服务(gateway/identity/metadata/data-pipeline)写 **Dockerfile** + 推**阿里云 ACR**(现无 Dockerfile,新增工作量)。

6. **【待 owner 拍板】ECS 常驻 vs 按需起停**:
   - **A. 按需起停**(CI 触发时 `terraform apply`/启停)——省成本,CI 时延 +几分钟;
   - **B. 常驻**——CI 快,但 ECS+RDS 常开计费。
   - 建议 A(省钱;CI 不频繁)。

7. **conftest 适配**:`tests/conftest.py:_reachable` 的 localhost skip 改为指向 ECS 地址(或 SSH 隧道把 ECS 端口映射回 runner localhost,最小改动)。

## Consequences
**正面**:CI 在真阿里云覆盖 prod parity(ADR-020 M-1 闭环);贴近 staging/prod、早暴露 parity 陷阱;Terraform 把现有手动云资源 IaC 化。
**负面/已知**:体量大(Terraform VPC/SG/ECS/RDS/CI 桶 + Dockerfile×4 + ACR + 新 CI workflow + conftest 改造 + 部署脚本 + 安全组调试)= **独立 sprint**;ECS/RDS 成本;CI 时延上升;SSH/凭据安全面新增(需 §5.2 严管)。

## Alternatives considered
- **仅把存储换阿里云 OSS、CI 仍用 GitHub runner 容器**(轻)—— owner 否决,要整套 ECS。
- **本地 MinIO 跑 CI**(最快免费)—— 覆盖不到真 OSS parity(ADR-020 M-1),不满足动因。
- **现在上 ACK** —— 过早、超人力,留 S2c。

## 分期与边界
- 本 ADR 拍板后 → **阶段 3 / 独立 Plan C** 实现(见批准方案);**不与阶段 2(本地配置/持久化)耦合**,`configs/test.yaml`(阶段 2 产)是 Plan C 输入。
- 过渡期:ECS 没建好前,CI 维持现状(`ci.yml` 用 compose 起 MinIO+KC),不破坏。

## 修订记录
- 2026-06-23 提出,待 owner 逐条拍板(尤其 §1 形态、§6 常驻/按需)。拍板后转 Accepted,作为 Plan C(阿里云 ECS CI)地基。
