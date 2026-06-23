# ADR-021: 环境配置体系(YAML profiles + libs/config 桥接 + 单一源)

- 状态:**Accepted（2026-06-23,owner 拍板)**
- 决策人:owner
- 相关:宪法 §5.2(密钥不进仓库)/ §5.3(配置外置 + dev/staging/prod 同构)/ §3(地基决策落 ADR);ADR-016(Gravitino 租户);`libs/audit/oss_audit.py:oss_boto3_config`;实测"混合串味"事件(gateway/identity/metadata 指真阿里云、data-pipeline 指本地,源于无单一配置源)

---

## Context
配置现状是**纯 `os.environ` 散读、无配置文件**;env 分散在 `Makefile` 的 `run-*` 内联与 `scripts/dev_services.sh:_env_for()` 两处各写一份。后果(实测):一次启动里**部分服务指向真阿里云 OSS、部分指向本地 MinIO**(metadata 审计会误写真云桶)——即"混合串味"。同时需要 **local / test(CI)/ prod 多环境**切换,且 dev 要本地持久化。这违反宪法 §5.3「配置外置 + 环境对等」,根因是**没有单一配置源**。

## Decision

1. **YAML profiles 为单一真相源**:`configs/{local,test,prod}.yaml`(分组:services URL / ports / oidc / auth.jwks / bff / oss.{endpoint,region,buckets,ttl} / gravitino / pipeline.{jobs_dir,raw_dir,dj_bin} / frontend.dist)。owner 选 YAML(优于 .env 的结构化可读)。

2. **`libs/config/` 加载器 + 桥接**(放分层最底层,合法;`pyyaml>=6` 已是依赖,零新增):
   - `load_settings(env=$LITEAI_ENV)`:读 `configs/<env>.yaml` → `os.environ` 展开 `${VAR}` 密钥占位 → 返回 typed dataclass。
   - `export_env(settings) -> {扁平 env}`:摊平成**现有 env 名**(`OSS_ENDPOINT`/`GRAVITINO_URL`/`LITEAI_JWKS_URL`/`BFF_SESSION_KEY`/`IDENTITY_ORG_URL`…),由 `scripts/load_env.py` 注入进程 → **服务现有 `os.environ` 读法一行不改即工作**。
   - **typed 访问(`os.environ` → `libs/config`)按需渐进迁移,不在本轮**;桥接保证过渡期值正确。

3. **密钥不进仓库(§5.2)**:YAML 只放 `${VAR}` 占位。**local 档**允许内联 dev 固定值(`minio/minio123`、`dev-web-secret`、dev BFF key——非真密钥,§5.3 允许 dev 固定);**test/prod 档**占位未由外部 env/secret 注入时 `load_settings` **fail-fast 报错**(对齐 `deploy/test/docker-compose.yml` 的 `${VAR:?}` 风格,不静默用空)。

4. **单一源保证(消灭串味)**:`Makefile` 加 `ENV ?= local`;`run-*` 与 `dev_services.sh:_env_for()` 删内联,改为"选 ENV → 加载同一个 `configs/$ENV.yaml`"。**一次启动只生效一个 profile**,物理上不可能再半云半本地。

5. **OSS client 复用**:仍走 `libs/audit/oss_audit.py:oss_boto3_config(endpoint)`(按 endpoint 自适配 path/virtual-hosted),配置层不重写 addressing style。

6. **dev Keycloak 持久化后端 = Postgres(owner 拍板)**:dev 也用 Postgres 后端(同 `deploy/test/docker-compose.yml`),dev/staging/prod 三档**同构**(§5.3 加分);代价是 dev compose 多一个 `postgres` 容器 + `KC_DB_*` 配置 + named volume(`kc-pgdata`)。否决 H2-file(同构性优先于 dev 轻量)。

## Consequences
**正面**:串味根除(单一源);local/test/prod 一键切;dev 数据持久;近零代码改动落地(桥接保 `os.environ` 契约);配置外置满足 §5.3。
**负面/已知**:新增 `libs/config/` + `configs/*.yaml` + `scripts/load_env.py`;`os.environ` 散读暂留(typed 迁移延后);`prod.yaml` 本轮仅骨架 + 显式 TBD(不静默留空)。

## Alternatives considered
- **`.env` profiles** —— owner 否决,要 YAML 结构化/可读。
- **TOML** —— 否决:仓库无 TOML 先例,且 docker-compose/shell/`os.environ` 都不读 TOML,要自建加载器 + 翻译喂 compose,徒增复杂。
- **pydantic-settings** —— 否决:引新依赖;`pyyaml`(已在)+ dataclass 已够,保持轻。
- **一次性全替换 `os.environ` → typed** —— 否决:改 10+ 文件 + 所有 monkeypatch 测试,高风险大爆炸;桥接 + 渐进迁移更稳。

## 修订记录
- 2026-06-23 提出,owner 拍板:§6 dev Keycloak 后端 = **Postgres(同构)**;转 **Accepted**。作为阶段 2(配置体系 + dev 持久化 + dev-only 隔离)地基。
