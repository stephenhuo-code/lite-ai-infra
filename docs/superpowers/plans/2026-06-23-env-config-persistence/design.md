# Design — 环境配置体系 + dev 持久化 + dev-only 隔离(Plan B / 阶段 2)

> HOW。地基 [ADR-021](../../../adr/ADR-021-env-config-system.md)(Accepted)。需求见同目录 [spec.md](./spec.md)。**引用既有家、不复制**。

## 架构与隔离

### 配置脊柱(单一源 + 桥接)
```
configs/<env>.yaml  ──load_settings(env)──>  Settings(dataclass)
   (人写真相源)            (libs/config)            │
                                                  export_env(Settings) ──> {扁平 env dict}
                                                                              │
                  scripts/load_env.py  ──注入 os.environ / 打印 export 行──────┘
                                                  │
        Makefile run-* / dev_services.sh  ──env $(load_env <svc>) uv run uvicorn ...──> 各服务
                                                  │
                          服务现有 os.environ.get("OSS_ENDPOINT") 等  ← 一行不改即工作
```
- **唯一真相源** = `configs/{local,test,prod}.yaml`。删除现存两处重复:`scripts/dev_services.sh:_env_for()` 与 `Makefile:run-*` 内联 env(实测逐字重复,FR-003/SC-004)。
- **桥接保 `os.environ` 契约**(FR-008):不改任何服务读法;`export_env` 把 YAML 摊平成服务现有 env 名(**基线 = `_env_for` 实测 echo 出的键集**,逐键 diff,不钉死数字)。
- **环境选择单开关** = `LITEAI_ENV`(默认 `local`),`Makefile` 加 `ENV ?= local` 透传(FR-002/SC-003)。

### 隔离不变式(对齐宪法 §1.6 / ADR-021)
- **本地启动路径**(`make up`/`run-*`/`dev_services.sh`)一次只 `load_settings` 一个 env → 物理上不可能半云半本地(FR-004/SC-001)。这是本轮真正接入桥接的唯一启动路径。
- test/prod 的**真实启动接入属阶段 3**(它们今天经 `deploy/test/docker-compose.yml` 的 `${VAR:?}`+.env 启动,不经 `libs/config`);本轮只产出 `configs/{test,prod}.yaml` 作为阶段 3 输入 + 用单测保证其 fail-fast 语义(SC-005),**不声称**本轮已为 test/prod 启动消灭串味。
- `configs/local.yaml` 内所有存储/下游端点均 localhost;任何 `*.aliyuncs.com` 只可能出现在 `test/prod.yaml`。

## libs/config(分层最底层,合法)
`.importlinter` 层序 `services > pipelines > libs`,`libs/config` 在 `libs` 底层,无反向依赖。零新依赖(`pyyaml>=6` 已在 `pyproject.toml`)。

### 公开接口(契约)
```python
# libs/config/__init__.py
def load_settings(env: str | None = None) -> Settings:
    """env 缺省取 $LITEAI_ENV,再缺省 'local'。读 configs/<env>.yaml →
    展开 ${VAR} 占位(来自 os.environ)→ 校验 → 返回 Settings。
    非 local 环境且必需 ${VAR} 未注入 → 抛 ConfigError(指出缺哪个 key)。"""

def export_env(s: Settings) -> dict[str, str]:
    """把 Settings 摊平成服务现有 env 名;按服务可取子集(见 SERVICE_ENV_KEYS)。"""
```
- `Settings` = 嵌套 dataclass,分组镜像 YAML:`services`(identity/metadata/data_pipeline/gateway URL)、`ports`、`auth`(jwks/issuer/audience)、`bff`(session_key/redirect_uri/cookie_secure/oidc_*)、`oss`(endpoint/region/access_key/secret_key/session_token/data_bucket/audit_bucket/upload_url_ttl)、`gravitino`(url)、`pipeline`(jobs_dir/raw_dir/dj_bin/dj_np)。
- **`${VAR}` 展开规则**:值形如 `${OSS_SECRET_KEY}` → 查 `os.environ`;命中则用,未命中:`local` 档报错(配置写错,local 不该有占位),`test/prod` 档抛 `ConfigError`(对齐 `deploy/test/docker-compose.yml` 的 `${VAR:?}` 语义,FR-007/SC-005)。字面值直接用。
- **`export_env` 路由**:每服务只需自己那部分 env(沿用 `_env_for` 的按服务子集逻辑)。`SERVICE_ENV_KEYS: dict[str, list[str]]` 定义 identity/metadata/data-pipeline/gateway 各取哪些扁平键 → 保持与今天 `_env_for` 完全一致的注入集(回归基线)。**基线以"`_env_for` 实测 echo 出的键集"为准**(逐键 diff,不钉死数字)。
- **回归基线不变量(worker 继承)**:data-pipeline 作业的真实执行体是 `worker.py`,经 `scheduler.py` 的 `subprocess.Popen` 派生、**靠继承父进程(data-pipeline 服务)的 env** 拿到对象存储凭据(detached,脱离服务进程组)。因此 **data-pipeline 的 `export_env` 子集 MUST 含 worker 运行所需的对象存储全集**(`OSS_ENDPOINT/OSS_ACCESS_KEY/OSS_SECRET_KEY/DATA_BUCKET/AUDIT_BUCKET` + 可选 `OSS_SESSION_TOKEN/OSS_REGION`);worker **不另设** `load_env.py` 注入路径。验收以 SC-008(真跑一次作业到成功)兜底——dev 单测/仅起服务测不出此继承缺口。

## scripts/load_env.py(桥接命令)
- 用法:`load_env.py <service>` → 打印 `KEY=VALUE`(空格分隔,供 `env $(...)` 消费),或 `--export` 打印 `export KEY=VALUE`(供 `eval`)。
- 读 `$LITEAI_ENV`(或 `$ENV`)→ `load_settings` → `export_env` → 取 `<service>` 子集。
- `dev_services.sh:_env_for(name)` 改为 `python scripts/load_env.py "$name"`;`Makefile:run-*` 改为 `env $$(uv run python scripts/load_env.py <svc>) uv run uvicorn ...`。**唯一注入路径**(FR-003)。

## 数据模型 / 配置 schema(YAML 形态)
`configs/local.yaml`(全填本地固定值,示意分组——非最终字段表,实现以 `_env_for`/`run-*` 现值为基线 1:1 搬入):
```yaml
env: local
services: { identity_url: http://localhost:8001, metadata_url: ..., data_pipeline_url: ..., gateway_url: http://localhost:8090 }
ports:    { identity: 8001, metadata: 8002, data_pipeline: 8003, gateway: 8090 }
auth:     { jwks_url: http://localhost:8080/realms/lite-ai/protocol/openid-connect/certs }
bff:      { session_key: <dev 固定>, redirect_uri: http://localhost:8090/auth/callback, oidc_client_id: lite-ai-web, oidc_client_secret: dev-web-secret, oidc_issuer: http://localhost:8080/realms/lite-ai }
oss:      { endpoint: http://localhost:9000, region: us-east-1, access_key: minio, secret_key: minio123, data_bucket: lite-ai, audit_bucket: lite-ai }
gravitino:{ url: http://localhost:8091 }
pipeline: { jobs_dir: ./.dev/jobs, dj_bin: ./.dj-venv/bin/dj-process }
```
`configs/test.yaml`:端点改阿里云占位,密钥用 `${OSS_ACCESS_KEY}`/`${OSS_SECRET_KEY}` 等占位(缺失 fail-fast);`configs/prod.yaml`:同结构,未定项写 `# TBD: <说明>` 显式占位(FR-009),不静默留空。

**不变量**:三档**同字段集**(键齐平,值不同),保证 dev/staging/prod 同构(宪法 §5.3);本轮新增字段必须三档同步。

## dev 持久化(US2 / FR-005)
镜像 `deploy/test/docker-compose.yml` 的已验证模式(它已是 Keycloak-on-Postgres + `kc-pgdata` 卷的可用模板):
- **Keycloak → Postgres 后端**(ADR-021 §6 owner 拍板):`deploy/dev/docker-compose.yml` 加 `postgres` 服务(`postgres:16-alpine` + `kc-pgdata` 卷 + healthcheck)、Keycloak 加 `KC_DB/KC_DB_URL/KC_DB_USERNAME/KC_DB_PASSWORD` + `depends_on: postgres healthy`。dev 的 DB 密码用本地固定值(非真密钥)。**realm import 行为不变**(保留 `--import-realm` + `:/opt/keycloak/data/import:ro`)。
- **MinIO → 持久卷**:`minio` 加 `minio-data:/data`(命名卷)。
- **Gravitino → 持久卷**:加 `gravitino-data:<容器内数据目录>` —— **数据目录路径 = 待探查项 P-1**(见下),实测钉死后写入。
- **停法分两种**(FR-005 AC2):新增/区分"保数据停"(`docker compose down`,不带 `-v`)与"清空停"(`down -v`)。当前 `make dev-down`/`make down` 带 `-v` 会删卷 —— 改为默认**不删卷**,清空走单独显式目标(如 `make dev-reset`)。

## dev-only 隔离(US3 / FR-006)
- **基础档**(`make deps-base`):`deploy/dev/docker-compose.yml`(MinIO + Keycloak + Postgres)—— CI 过渡期也只需这些。
- **完整档**(`make deps-dev`):基础档 + `gravitino.yml` + (可选)`swagger-ui.yml`。
- **叠加而非单起**:`gravitino.yml` 声明 `networks.dev_default {external: true, name: dev_default}`(gravitino.yml:11-13),该网络由基础档 compose(project `dev`)首次 `up` 创建。故 `deps-dev` MUST = **先起基础档、再叠加 overlay**(同 compose project,或显式 `--project-name dev`),**不可单独起 overlay**(否则 external 网络不存在,Gravitino 起不来)。`make up` = 完整档 + 起服务进程(行为对开发者不变)。

## 授权 / 安全 / 红线
- **密钥不入库**(宪法 §5.2/FR-007):YAML 仅本地固定 dev 值 + 非本地 `${VAR}` 占位;真密钥经 `os.environ`/外部 secret 注入。
- `BFF_COOKIE_SECURE`、`OSS_SESSION_TOKEN` 等可选项:缺省值由 `Settings` 字段默认承载,不在 YAML 强制。
- 测试注入类 env(`LITEAI_SUB`/`LITEAI_GROUPS`/`LITEAI_ALLOW_TEST_CLAIMS`/`LITEAI_TOKEN_*`)**不进 profile** —— 它们是测试夹具注入,非环境配置,保持现状由测试自行设置。

## NFR
- **dev/prod parity**(§5.3):三档同构 schema;dev Keycloak 用 Postgres(同 staging/prod);OSS client 仍走 `libs/audit/oss_audit.py:oss_boto3_config(endpoint)` 按 endpoint 自适配 addressing style,配置层不重写。
- **兼容/低风险**:`os.environ` 读法零改动;`export_env` 注入集与今天 `_env_for` 逐键比对一致(回归基线)。
- **部署拓扑**:本轮仅 dev compose + 本地进程;CI 维持现状(`.github/workflows/ci.yml` 不改),阿里云属阶段 3。

## 待探查项(DoR #4,带决策规则)
- **P-1 Gravitino 1.1.0 数据/元数据目录**:起容器 → `docker exec` 查其 fileset catalog 元数据落盘路径(候选 `/root/gravitino/data` 或工作目录下 `data/`)。**决策规则**:实测确认的目录 → 挂 `gravitino-data:<该目录>`,且**该卷必须与基础档卷同属 compose project `dev`**(确保"保数据停" `down` 不删它、"清空停" `dev-reset` 能一并清——卷的 project 归属决定 `down -v` 删不删得到);若 1.1.0 默认纯内存/无独立持久目录 → 记 RESULTS 并把 Gravitino 持久化标为 v Next(**US2 缩到 MinIO+KC 两类**,spec US2-AC1/SC-002 对应改"两类",owner 已预批此分支)。
- **P-2 Keycloak-on-Postgres dev 实测**:按 `deploy/test/docker-compose.yml` 模式起 dev,`down`(不 -v)→ `up` → 确认 realm/用户保留。**决策规则**:保留成功 → 采纳;失败 → 排查 import 与卷冲突(`/opt/keycloak/data/import:ro` 不得覆盖 `/opt/keycloak/data` 持久内容)。
- **P-3 MinIO 卷挂载与 import 子挂载不冲突**:确认 `minio-data:/data` 与现有无子挂载冲突(MinIO 无 import 子挂载,低风险,顺带验证)。

## 验收 / 测试策略
- **单元**:`libs/config` —— `load_settings` 正常解析 local;`${VAR}` 命中/未命中(local 报错 vs test fail-fast);`export_env` 输出键集 == 基线键集(对每个服务断言键集与旧 `_env_for` 一致)。
- **集成/手动**(对应 SC-001/002/006/008):见 plan 的 owner-readable runbook —— ① 起本地全栈,核对所有服务存储端点同源本地;② 造数→保数据重启→三类(或缩两类,视 P-1)数据仍在;③ 基础档 vs 完整档容器集合核对;④ **真跑一次数据作业到成功**(SC-008,验 worker 继承)。注:SC-005(test 缺密钥失败)由**单测**覆盖,非手动启动(C-1 范围说明)。
- **门禁(SC-007)**:新增 `libs/config` 单测纳入 `uv run pytest -q` 全绿;`make lint`(`lint-imports` 校验 `libs/config` 分层合法,不引入反向依赖)+ `make gen` 不破;`ci_guards.sh` 仍过(其只查 display_name/enterprise_id,与本轮无关,仅确认不回归)。
- **DoD**:手动 runbook 全过(owner 可读、step-by-step)+ 自动门禁全绿 + 两处重复配置已删(`grep` 证明 `_env_for`/`run-*` 内联 env 不再各写一份,单一源)。

## 关键决策留痕
- [ADR-021](../../../adr/ADR-021-env-config-system.md)(Accepted):YAML profiles + 桥接 + 密钥外置 + 单一源;dev Keycloak=Postgres。否决方案(.env/TOML/pydantic-settings/一次性重写)已记。
- [ADR-022](../../../adr/ADR-022-ci-on-aliyun-ecs.md)(Proposed):CI=阿里云 ECS,阶段 3;本设计 `configs/test.yaml` 是其输入。
