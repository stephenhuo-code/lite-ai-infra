# 环境配置体系 + dev 持久化 + dev-only 隔离 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 `configs/{local,test,prod}.yaml` 单一配置源 + `libs/config` 加载器 + `scripts/load_env.py` 桥接,消灭"半云半本地串味",并给 dev 加 Postgres/命名卷做持久化、用 `deps-base`/`deps-dev` 划清 dev-only 隔离。

**Architecture:** YAML 档为唯一真相源 → `libs/config.load_settings(env)` 解析 + 展开 `${VAR}` 密钥占位 → `export_env` 摊平成服务现有 env 名 → `scripts/load_env.py` 注入进程。服务的 `os.environ` 读法**一行不改**(桥接兼容)。删除 `dev_services.sh:_env_for()` 与 `Makefile:run-*` 两处重复内联(单一源)。dev 持久化镜像 `deploy/test/docker-compose.yml` 已验证的 Keycloak-on-Postgres + 命名卷模式。

**Tech Stack:** Python 3 + PyYAML(已在依赖)+ dataclass;docker compose(MinIO/Keycloak/Postgres/Gravitino);Makefile + bash;pytest。

**地基:** [ADR-021](../adr/ADR-021-env-config-system.md)(Accepted)。spec/design:[`2026-06-23-env-config-persistence/spec.md`](./2026-06-23-env-config-persistence/spec.md) · [`design.md`](./2026-06-23-env-config-persistence/design.md)(已过 DoR)。

**回归基线(实测锁定,Task 4/5 必须 1:1 复现):**
| 服务 | `_env_for` 注入的 env 键集(顺序无关) |
|---|---|
| identity | `LITEAI_JWKS_URL` |
| metadata | `LITEAI_JWKS_URL` `GRAVITINO_URL` |
| data-pipeline | `LITEAI_JWKS_URL` `JOBS_DIR` `OSS_ENDPOINT` `OSS_ACCESS_KEY` `OSS_SECRET_KEY` `OSS_REGION` `DATA_BUCKET` `AUDIT_BUCKET` `DJ_BIN` |
| gateway | `IDENTITY_ORG_URL` `METADATA_URL` `DATA_PIPELINE_URL` `LITEAI_JWKS_URL` `BFF_SESSION_KEY` `OIDC_CLIENT_ID` `OIDC_CLIENT_SECRET` `OIDC_ISSUER` `BFF_REDIRECT_URI` |

**worker 继承不变量(design I-1):** `worker.py` 经 `scheduler.py` 的 `subprocess.Popen` 派生、继承 data-pipeline 服务 env;它读 `OSS_ENDPOINT/OSS_ACCESS_KEY/OSS_SECRET_KEY/AUDIT_BUCKET/DATA_BUCKET`(+ 可选 `OSS_SESSION_TOKEN/OSS_REGION`)——全部已在 data-pipeline 基线集内,**不得遗漏**。SC-008 真跑一次作业兜底验证。

---

## File Structure

| 文件 | 责任 | 动作 |
|---|---|---|
| `libs/config/__init__.py` | `Settings` dataclass + `load_settings` + `export_env` + `SERVICE_ENV_KEYS` + `ConfigError` | Create |
| `configs/local.yaml` | 本地档(全填本地固定值) | Create |
| `configs/test.yaml` | 测试档(阿里云占位 + `${VAR}` 密钥) | Create |
| `configs/prod.yaml` | 生产档骨架(显式 `# TBD`) | Create |
| `scripts/load_env.py` | CLI:`<service>` → 打印该服务 env(供 `env $(...)`) | Create |
| `tests/config/test_loader.py` | load_settings/${VAR}/export_env/SERVICE_ENV_KEYS 单测 | Create |
| `scripts/dev_services.sh` | 去 `_env_for`,改调 `load_env.py` | Modify |
| `Makefile` | `ENV ?= local`;`run-*` 去内联;`deps-base`/`deps-dev`;保数据停 vs 清空停 | Modify |
| `deploy/dev/docker-compose.yml` | 加 `postgres` + `minio-data`/`kc-pgdata` 卷 + KC 接 Postgres | Modify |
| `deploy/dev/gravitino.yml` | 加 `gravitino-data` 卷(视 P-1) | Modify |
| `docs/superpowers/plans/2026-06-23-env-config-persistence/spikes/RESULTS.md` | 探针 P-1/P-2/P-3 实测结果 | Create |

---

## Task 1: 探针 P-1/P-2/P-3(持久化落盘事实)

> 探针任务,非 TDD。跑命令 → 记录实测 → 按决策规则定后续 Task 6/7 的卷路径。**先做,因为 Task 6 依赖其结果。**

**Files:**
- Create: `docs/superpowers/plans/2026-06-23-env-config-persistence/spikes/RESULTS.md`

- [ ] **Step 1: 探 P-2(Keycloak-on-Postgres dev 可行性)** —— 它有现成模板(`deploy/test/docker-compose.yml`),先验最稳的。

Run:
```bash
# 用 test 那份 compose 起一把(它已是 KC+Postgres),确认能起、realm 能 import
KC_DB_PASSWORD=devpw KC_ADMIN_USER=admin KC_ADMIN_PASSWORD=admin \
  docker compose -f deploy/test/docker-compose.yml up -d
sleep 25
docker compose -f deploy/test/docker-compose.yml ps
curl -fsS http://localhost:8080/realms/lite-ai/.well-known/openid-configuration >/dev/null && echo "REALM_OK" || echo "REALM_FAIL"
docker compose -f deploy/test/docker-compose.yml down   # 不带 -v,留卷
```
Expected: `REALM_OK`;`postgres` + `keycloak` 均 Up。记录到 RESULTS:KC-on-Postgres dev 可行 ✅/❌ + 镜像 tag。

- [ ] **Step 2: 探 P-3(MinIO 命名卷)** —— 确认 `minio-data:/data` 持久且无子挂载冲突。

Run:
```bash
docker run -d --name probe-minio -p 9000:9000 -v probe-minio-data:/data \
  -e MINIO_ROOT_USER=minio -e MINIO_ROOT_PASSWORD=minio123 minio/minio:latest server /data
sleep 5
docker exec probe-minio sh -c 'ls -la /data && touch /data/.probe && ls /data/.probe' && echo "MINIO_VOL_OK"
docker rm -f probe-minio   # 卷 probe-minio-data 保留即证持久;清理:docker volume rm probe-minio-data
docker volume rm probe-minio-data 2>/dev/null
```
Expected: `MINIO_VOL_OK`。记录:MinIO `:/data` 命名卷可行 ✅。

- [ ] **Step 3: 探 P-1(Gravitino 1.1.0 数据目录)** —— 真未知项;定持久化卷路径或触发"缩两类"分支。

Run:
```bash
docker run -d --name probe-grav -p 8091:8090 apache/gravitino:1.1.0
sleep 20
docker exec probe-grav sh -lc 'echo "--- pwd ---"; pwd; echo "--- 候选数据目录 ---"; ls -la ./data 2>/dev/null; ls -la /root/gravitino/data 2>/dev/null; echo "--- 进程工作目录 ---"; ls -la /root/gravitino 2>/dev/null || ls -la /opt/gravitino 2>/dev/null; echo "--- 配置里的 entity store 路径 ---"; find / -name "gravitino.conf" 2>/dev/null -exec grep -i "entity.store\|kv.rocksdb\|jdbc" {} \;'
docker logs probe-grav 2>&1 | grep -i "store\|data\|rocksdb\|path" | head
docker rm -f probe-grav
```
Expected: 找到 fileset catalog 元数据落盘目录(候选 `./data`、`/root/gravitino/data`)。

- [ ] **Step 4: 应用 P-1 决策规则,记录 RESULTS**

决策规则(design P-1):
- **若找到独立持久目录** `<DIR>` → Task 6 给 gravitino 挂 `gravitino-data:<DIR>`,且该卷归属 compose project `dev`(与 base 卷同 project,确保 `down` 不删、`dev-reset` 能清)。
- **若 1.1.0 无独立持久目录(纯内存/嵌入式无固定路径)** → **触发已预批的"缩两类"分支**:US2/SC-002 的持久化只覆盖 MinIO + Keycloak 两类,Gravitino 持久化标 v Next。Task 6 跳过 gravitino 卷,Task 8 runbook 第二步只验两类。

写 `RESULTS.md`:三探针结论 + Gravitino 数据目录路径(或"无,缩两类")+ 用到的镜像 tag。

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/plans/2026-06-23-env-config-persistence/spikes/RESULTS.md
git commit -m "spike(env-config): 探针 P-1/P-2/P-3 持久化落盘事实"
```

---

## Task 2: `libs/config` 加载器(Settings + load_settings + ${VAR} 展开)

**Files:**
- Create: `libs/config/__init__.py`
- Test: `tests/config/test_loader.py`

- [ ] **Step 1: 写失败测试(local 正常解析 + ${VAR} 规则)**

```python
# tests/config/test_loader.py
import os
import textwrap
import pytest
from libs.config import load_settings, ConfigError

def _write(tmp_path, name, body):
    d = tmp_path / "configs"; d.mkdir(exist_ok=True)
    (d / name).write_text(textwrap.dedent(body)); return tmp_path

def test_load_local_resolves_literal_values(tmp_path, monkeypatch):
    root = _write(tmp_path, "local.yaml", """
        env: local
        oss: {endpoint: 'http://localhost:9000', access_key: minio, secret_key: minio123,
              region: us-east-1, data_bucket: lite-ai, audit_bucket: lite-ai}
        auth: {jwks_url: 'http://localhost:8080/x'}
        services: {identity_url: 'http://localhost:8001', metadata_url: 'http://localhost:8002',
                   data_pipeline_url: 'http://localhost:8003', gateway_url: 'http://localhost:8090'}
        bff: {session_key: devkey, redirect_uri: 'http://localhost:8090/auth/callback',
              oidc_client_id: lite-ai-web, oidc_client_secret: dev-web-secret,
              oidc_issuer: 'http://localhost:8080/realms/lite-ai'}
        gravitino: {url: 'http://localhost:8091'}
        pipeline: {jobs_dir: ./.dev/jobs, dj_bin: ./.dj-venv/bin/dj-process}
    """)
    s = load_settings("local", root=root)
    assert s.oss.endpoint == "http://localhost:9000"
    assert s.oss.access_key == "minio"

def test_test_env_missing_secret_fails_fast(tmp_path, monkeypatch):
    monkeypatch.delenv("OSS_SECRET_KEY", raising=False)
    root = _write(tmp_path, "test.yaml", """
        env: test
        oss: {endpoint: 'https://oss-cn-hangzhou.aliyuncs.com', access_key: '${OSS_ACCESS_KEY}',
              secret_key: '${OSS_SECRET_KEY}', region: cn-hangzhou, data_bucket: t, audit_bucket: t}
        auth: {jwks_url: 'https://x/certs'}
        services: {identity_url: 'http://i', metadata_url: 'http://m',
                   data_pipeline_url: 'http://d', gateway_url: 'http://g'}
        bff: {session_key: '${BFF_SESSION_KEY}', redirect_uri: 'http://g/auth/callback',
              oidc_client_id: w, oidc_client_secret: '${OIDC_CLIENT_SECRET}', oidc_issuer: 'http://x'}
        gravitino: {url: 'http://grav'}
        pipeline: {jobs_dir: /var/jobs, dj_bin: /usr/bin/dj-process}
    """)
    with pytest.raises(ConfigError) as ei:
        load_settings("test", root=root)
    assert "OSS_SECRET_KEY" in str(ei.value)

def test_test_env_with_secret_injected_ok(tmp_path, monkeypatch):
    monkeypatch.setenv("OSS_ACCESS_KEY", "AK"); monkeypatch.setenv("OSS_SECRET_KEY", "SK")
    monkeypatch.setenv("BFF_SESSION_KEY", "BK"); monkeypatch.setenv("OIDC_CLIENT_SECRET", "CS")
    root = _write(tmp_path, "test.yaml", """
        env: test
        oss: {endpoint: 'https://oss-cn-hangzhou.aliyuncs.com', access_key: '${OSS_ACCESS_KEY}',
              secret_key: '${OSS_SECRET_KEY}', region: cn-hangzhou, data_bucket: t, audit_bucket: t}
        auth: {jwks_url: 'https://x/certs'}
        services: {identity_url: 'http://i', metadata_url: 'http://m',
                   data_pipeline_url: 'http://d', gateway_url: 'http://g'}
        bff: {session_key: '${BFF_SESSION_KEY}', redirect_uri: 'http://g/auth/callback',
              oidc_client_id: w, oidc_client_secret: '${OIDC_CLIENT_SECRET}', oidc_issuer: 'http://x'}
        gravitino: {url: 'http://grav'}
        pipeline: {jobs_dir: /var/jobs, dj_bin: /usr/bin/dj-process}
    """)
    s = load_settings("test", root=root)
    assert s.oss.secret_key == "SK"

def test_local_env_with_unfilled_placeholder_is_error(tmp_path):
    # local 档不该有占位:出现 ${VAR} 即配置写错
    root = _write(tmp_path, "local.yaml", """
        env: local
        oss: {endpoint: 'http://localhost:9000', access_key: minio, secret_key: '${OSS_SECRET_KEY}',
              region: us-east-1, data_bucket: lite-ai, audit_bucket: lite-ai}
        auth: {jwks_url: 'http://x'}
        services: {identity_url: 'http://i', metadata_url: 'http://m',
                   data_pipeline_url: 'http://d', gateway_url: 'http://g'}
        bff: {session_key: k, redirect_uri: 'http://g/cb', oidc_client_id: w,
              oidc_client_secret: s, oidc_issuer: 'http://x'}
        gravitino: {url: 'http://grav'}
        pipeline: {jobs_dir: ./.dev/jobs, dj_bin: ./x}
    """)
    with pytest.raises(ConfigError):
        load_settings("local", root=root)
```

- [ ] **Step 2: 运行,确认失败**

Run: `uv run pytest tests/config/test_loader.py -q`
Expected: FAIL（`ModuleNotFoundError: libs.config` 或 `cannot import name`）

- [ ] **Step 3: 实现 `libs/config/__init__.py`(Settings + load_settings)**

```python
# libs/config/__init__.py
"""单一配置源:configs/<env>.yaml → 解析 + 展开 ${VAR} → 强类型 Settings。
设计见 docs/superpowers/plans/2026-06-23-env-config-persistence/design.md(ADR-021)。"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, fields, is_dataclass
from pathlib import Path

import yaml

_PLACEHOLDER = re.compile(r"^\$\{([A-Z_][A-Z0-9_]*)\}$")
_REPO_ROOT = Path(__file__).resolve().parents[2]


class ConfigError(RuntimeError):
    """配置缺失/占位未注入/档不存在。"""


@dataclass
class _Services:
    identity_url: str
    metadata_url: str
    data_pipeline_url: str
    gateway_url: str


@dataclass
class _Auth:
    jwks_url: str


@dataclass
class _Bff:
    session_key: str
    redirect_uri: str
    oidc_client_id: str
    oidc_client_secret: str
    oidc_issuer: str


@dataclass
class _Oss:
    endpoint: str
    access_key: str
    secret_key: str
    region: str
    data_bucket: str
    audit_bucket: str
    session_token: str | None = None
    upload_url_ttl: int | None = None


@dataclass
class _Gravitino:
    url: str


@dataclass
class _Pipeline:
    jobs_dir: str
    dj_bin: str
    raw_dir: str | None = None


@dataclass
class Settings:
    env: str
    services: _Services
    auth: _Auth
    bff: _Bff
    oss: _Oss
    gravitino: _Gravitino
    pipeline: _Pipeline


def _expand(value, env_name: str, missing: list[str]):
    """字面值直返;${VAR} 查 os.environ,未命中记入 missing(后续按 env 决定是否致命)。"""
    if isinstance(value, str):
        m = _PLACEHOLDER.match(value)
        if m:
            var = m.group(1)
            got = os.environ.get(var)
            if got is None:
                missing.append(var)
                return None
            return got
    return value


def _build(cls, data: dict, env_name: str, missing: list[str]):
    kwargs = {}
    for f in fields(cls):
        if f.name not in data:
            continue
        raw = data[f.name]
        if is_dataclass(f.type) if not isinstance(f.type, str) else False:
            kwargs[f.name] = _build(f.type, raw, env_name, missing)
        else:
            kwargs[f.name] = _expand(raw, env_name, missing)
    return cls(**kwargs)


def load_settings(env: str | None = None, root: Path | None = None) -> Settings:
    """读 configs/<env>.yaml → 展开 ${VAR} → Settings。
    env 缺省取 $LITEAI_ENV 再缺省 'local'。
    local 档出现未命中占位 = 配置写错(本地不该有占位)→ ConfigError。
    非 local 档占位未注入 → ConfigError(指出缺哪些,对齐 ${VAR:?} 语义)。"""
    env = env or os.environ.get("LITEAI_ENV") or "local"
    root = root or _REPO_ROOT
    path = Path(root) / "configs" / f"{env}.yaml"
    if not path.exists():
        raise ConfigError(f"配置档不存在: {path}")
    data = yaml.safe_load(path.read_text()) or {}
    missing: list[str] = []
    # 嵌套子表逐个构建(显式,避免 dataclass 类型字符串注解的反射坑)
    settings = Settings(
        env=data.get("env", env),
        services=_Services(**{k: _expand(v, env, missing) for k, v in (data.get("services") or {}).items()}),
        auth=_Auth(**{k: _expand(v, env, missing) for k, v in (data.get("auth") or {}).items()}),
        bff=_Bff(**{k: _expand(v, env, missing) for k, v in (data.get("bff") or {}).items()}),
        oss=_Oss(**{k: _expand(v, env, missing) for k, v in (data.get("oss") or {}).items()}),
        gravitino=_Gravitino(**{k: _expand(v, env, missing) for k, v in (data.get("gravitino") or {}).items()}),
        pipeline=_Pipeline(**{k: _expand(v, env, missing) for k, v in (data.get("pipeline") or {}).items()}),
    )
    if missing:
        raise ConfigError(
            f"[{env}] 必需配置占位未注入: {', '.join(sorted(set(missing)))} "
            f"(经环境变量或外部 secret 提供;{env} 档不得静默用空值)"
        )
    return settings
```

> 注:`_build`/`is_dataclass` 辅助保留备用,实际 `load_settings` 用显式逐表构建(更可读、避开注解反射)。实现时可删未用的 `_build`/`_expand` 重复——保持 YAGNI。

- [ ] **Step 4: 运行,确认通过**

Run: `uv run pytest tests/config/test_loader.py -q`
Expected: PASS（4 passed）

- [ ] **Step 5: Commit**

```bash
git add libs/config/__init__.py tests/config/test_loader.py
git commit -m "feat(config): libs/config 加载器(Settings + load_settings + \${VAR} fail-fast)"
```

---

## Task 3: `configs/{local,test,prod}.yaml`(三档同字段)

**Files:**
- Create: `configs/local.yaml` `configs/test.yaml` `configs/prod.yaml`

- [ ] **Step 1: 写 `configs/local.yaml`(本地固定值,1:1 搬自现 `_env_for`/`run-*`)**

```yaml
# configs/local.yaml —— 完全本地档(单一源)。固定值均为 dev 非真密钥(宪法 §5.3 允许)。
env: local
services:
  identity_url: http://localhost:8001
  metadata_url: http://localhost:8002
  data_pipeline_url: http://localhost:8003
  gateway_url: http://localhost:8090
auth:
  jwks_url: http://localhost:8080/realms/lite-ai/protocol/openid-connect/certs
bff:
  session_key: 5SetoEInIYji6K_tuQEB8pJ8NCaoC5yi2vNAxtPi7gg=
  redirect_uri: http://localhost:8090/auth/callback
  oidc_client_id: lite-ai-web
  oidc_client_secret: dev-web-secret
  oidc_issuer: http://localhost:8080/realms/lite-ai
oss:
  endpoint: http://localhost:9000
  access_key: minio
  secret_key: minio123
  region: us-east-1
  data_bucket: lite-ai
  audit_bucket: lite-ai
gravitino:
  url: http://localhost:8091
pipeline:
  jobs_dir: ./.dev/jobs
  dj_bin: ./.dj-venv/bin/dj-process
```

- [ ] **Step 2: 写 `configs/test.yaml`(阿里云占位 + 密钥 `${VAR}`)**

```yaml
# configs/test.yaml —— 测试(阿里云 ECS)档骨架。阶段 3(ADR-022)接入真实启动;本轮仅为其输入。
# 密钥经环境/外部 secret 注入(${VAR});缺失则 load_settings fail-fast。
env: test
services:
  identity_url: http://identity:8001        # TBD(阶段 3):ECS 内网地址
  metadata_url: http://metadata:8002        # TBD(阶段 3)
  data_pipeline_url: http://data-pipeline:8003  # TBD(阶段 3)
  gateway_url: http://gateway:8090          # TBD(阶段 3)
auth:
  jwks_url: http://keycloak:8080/realms/lite-ai/protocol/openid-connect/certs  # TBD(阶段 3):ECS KC 地址
bff:
  session_key: ${BFF_SESSION_KEY}
  redirect_uri: http://gateway:8090/auth/callback  # TBD(阶段 3)
  oidc_client_id: lite-ai-web
  oidc_client_secret: ${OIDC_CLIENT_SECRET}
  oidc_issuer: http://keycloak:8080/realms/lite-ai  # TBD(阶段 3)
oss:
  endpoint: https://oss-cn-hangzhou.aliyuncs.com  # 真阿里云 OSS(parity 复验,ADR-020)
  access_key: ${OSS_ACCESS_KEY}
  secret_key: ${OSS_SECRET_KEY}
  region: cn-hangzhou
  data_bucket: ${CI_DATA_BUCKET}             # 独立 CI 桶(ADR-022 §3)
  audit_bucket: ${CI_AUDIT_BUCKET}
gravitino:
  url: http://gravitino:8090                 # TBD(阶段 3):ECS Gravitino 地址
pipeline:
  jobs_dir: /var/lib/lite-ai/jobs            # TBD(阶段 3):ECS 路径
  dj_bin: /opt/dj-venv/bin/dj-process        # TBD(阶段 3)
```

- [ ] **Step 3: 写 `configs/prod.yaml`(骨架 + 显式 TBD,不静默留空)**

```yaml
# configs/prod.yaml —— 生产档骨架。未定项显式 TBD(spec FR-009);prod 上线前补齐 + 走 ADR/runbook 硬化。
env: prod
services:
  identity_url: # TBD(prod):内网服务地址
  metadata_url: # TBD(prod)
  data_pipeline_url: # TBD(prod)
  gateway_url: # TBD(prod):对外域名
auth:
  jwks_url: # TBD(prod):prod Keycloak JWKS
bff:
  session_key: ${BFF_SESSION_KEY}
  redirect_uri: # TBD(prod):https 回调
  oidc_client_id: lite-ai-web
  oidc_client_secret: ${OIDC_CLIENT_SECRET}
  oidc_issuer: # TBD(prod)
oss:
  endpoint: # TBD(prod):prod OSS endpoint
  access_key: ${OSS_ACCESS_KEY}
  secret_key: ${OSS_SECRET_KEY}
  region: # TBD(prod)
  data_bucket: # TBD(prod)
  audit_bucket: # TBD(prod)
gravitino:
  url: # TBD(prod)
pipeline:
  jobs_dir: # TBD(prod)
  dj_bin: # TBD(prod)
```

- [ ] **Step 4: 加 local 档烟测(三档存在 + local 可解析)**

追加到 `tests/config/test_loader.py`:
```python
def test_repo_local_yaml_loads():
    # 仓库真 configs/local.yaml 必须能在无任何 env 注入下解析(本地不依赖密钥)
    s = load_settings("local")
    assert s.oss.endpoint == "http://localhost:9000"
    assert s.gravitino.url == "http://localhost:8091"
    assert "aliyuncs" not in s.oss.endpoint   # local 绝不指云(SC-001)
```

- [ ] **Step 5: 运行 + Commit**

Run: `uv run pytest tests/config/test_loader.py -q`
Expected: PASS（5 passed）
```bash
git add configs/local.yaml configs/test.yaml configs/prod.yaml tests/config/test_loader.py
git commit -m "feat(config): configs/{local,test,prod}.yaml 三档(local 全填/test 占位/prod 骨架)"
```

---

## Task 4: `export_env` + `SERVICE_ENV_KEYS`(回归基线 1:1)

**Files:**
- Modify: `libs/config/__init__.py`
- Test: `tests/config/test_loader.py`

- [ ] **Step 1: 写失败测试(每服务键集 == 回归基线)**

追加:
```python
from libs.config import export_env, SERVICE_ENV_KEYS

_BASELINE = {
    "identity": {"LITEAI_JWKS_URL"},
    "metadata": {"LITEAI_JWKS_URL", "GRAVITINO_URL"},
    "data-pipeline": {"LITEAI_JWKS_URL", "JOBS_DIR", "OSS_ENDPOINT", "OSS_ACCESS_KEY",
                      "OSS_SECRET_KEY", "OSS_REGION", "DATA_BUCKET", "AUDIT_BUCKET", "DJ_BIN"},
    "gateway": {"IDENTITY_ORG_URL", "METADATA_URL", "DATA_PIPELINE_URL", "LITEAI_JWKS_URL",
                "BFF_SESSION_KEY", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET", "OIDC_ISSUER",
                "BFF_REDIRECT_URI"},
}

@pytest.mark.parametrize("svc,keys", _BASELINE.items())
def test_export_env_matches_baseline(svc, keys):
    s = load_settings("local")
    env = export_env(s, svc)
    assert set(env.keys()) == keys, f"{svc} 键集偏离回归基线"
    assert all(v for v in env.values()), f"{svc} 有空值"

def test_data_pipeline_subset_covers_worker_oss_set():
    # worker 经 Popen 继承,OSS 全集必须在 data-pipeline 子集内(design I-1 不变量)
    s = load_settings("local")
    env = export_env(s, "data-pipeline")
    for k in ("OSS_ENDPOINT", "OSS_ACCESS_KEY", "OSS_SECRET_KEY", "DATA_BUCKET", "AUDIT_BUCKET"):
        assert k in env

def test_data_pipeline_paths_are_absolute():
    # 路径解析为绝对(对齐 dev_services.sh 的 $ROOT/...,worker 子进程 cwd 无关)
    s = load_settings("local")
    env = export_env(s, "data-pipeline")
    assert env["JOBS_DIR"].startswith("/")
    assert env["DJ_BIN"].startswith("/")
```

- [ ] **Step 2: 运行,确认失败**

Run: `uv run pytest tests/config/test_loader.py -q`
Expected: FAIL（`cannot import name 'export_env'`)

- [ ] **Step 3: 实现 `export_env` + `SERVICE_ENV_KEYS`(追加到 `libs/config/__init__.py`)**

```python
# --- 桥接:Settings → 服务现有 env 名(回归基线 1:1) ---

# 扁平 env 名 → 取值函数(单一映射表;新增 env 在此加一行)
def _flat(s: "Settings") -> dict[str, str | None]:
    p = s.pipeline
    return {
        "LITEAI_JWKS_URL": s.auth.jwks_url,
        "GRAVITINO_URL": s.gravitino.url,
        "IDENTITY_ORG_URL": s.services.identity_url,
        "METADATA_URL": s.services.metadata_url,
        "DATA_PIPELINE_URL": s.services.data_pipeline_url,
        "BFF_SESSION_KEY": s.bff.session_key,
        "OIDC_CLIENT_ID": s.bff.oidc_client_id,
        "OIDC_CLIENT_SECRET": s.bff.oidc_client_secret,
        "OIDC_ISSUER": s.bff.oidc_issuer,
        "BFF_REDIRECT_URI": s.bff.redirect_uri,
        "OSS_ENDPOINT": s.oss.endpoint,
        "OSS_ACCESS_KEY": s.oss.access_key,
        "OSS_SECRET_KEY": s.oss.secret_key,
        "OSS_REGION": s.oss.region,
        "DATA_BUCKET": s.oss.data_bucket,
        "AUDIT_BUCKET": s.oss.audit_bucket,
        "JOBS_DIR": _abs(p.jobs_dir),
        "DJ_BIN": _abs(p.dj_bin),
    }


def _abs(path: str | None) -> str | None:
    if path is None:
        return None
    pp = Path(path)
    return str(pp if pp.is_absolute() else (_REPO_ROOT / pp))


# 每服务注入子集 == 现 _env_for 实测基线(顺序无关)
SERVICE_ENV_KEYS: dict[str, list[str]] = {
    "identity": ["LITEAI_JWKS_URL"],
    "metadata": ["LITEAI_JWKS_URL", "GRAVITINO_URL"],
    "data-pipeline": ["LITEAI_JWKS_URL", "JOBS_DIR", "OSS_ENDPOINT", "OSS_ACCESS_KEY",
                      "OSS_SECRET_KEY", "OSS_REGION", "DATA_BUCKET", "AUDIT_BUCKET", "DJ_BIN"],
    "gateway": ["IDENTITY_ORG_URL", "METADATA_URL", "DATA_PIPELINE_URL", "LITEAI_JWKS_URL",
                "BFF_SESSION_KEY", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET", "OIDC_ISSUER",
                "BFF_REDIRECT_URI"],
}


def export_env(s: "Settings", service: str) -> dict[str, str]:
    """返回该服务启动所需的扁平 env(== 现 _env_for 注入集)。"""
    if service not in SERVICE_ENV_KEYS:
        raise ConfigError(f"未知服务: {service}(可选:{', '.join(SERVICE_ENV_KEYS)})")
    flat = _flat(s)
    out = {}
    for k in SERVICE_ENV_KEYS[service]:
        v = flat.get(k)
        if v is None:
            raise ConfigError(f"服务 {service} 所需配置 {k} 为空(env={s.env})")
        out[k] = str(v)
    return out
```

- [ ] **Step 4: 运行,确认通过**

Run: `uv run pytest tests/config/test_loader.py -q`
Expected: PASS（全部 passed）

- [ ] **Step 5: Commit**

```bash
git add libs/config/__init__.py tests/config/test_loader.py
git commit -m "feat(config): export_env + SERVICE_ENV_KEYS(回归基线 1:1 + worker 继承不变量)"
```

---

## Task 5: `scripts/load_env.py` + 接线 `dev_services.sh`/`Makefile`(删两处重复 → 单一源)

**Files:**
- Create: `scripts/load_env.py`
- Modify: `scripts/dev_services.sh:18-29`(删 `_env_for` 内联)
- Modify: `Makefile:13,22-25`(`run-*` 去内联)
- Test: `tests/config/test_loader.py`(load_env CLI 烟测)

- [ ] **Step 1: 写失败测试(CLI 输出形如 `KEY=VALUE` 且含基线键)**

追加:
```python
import subprocess, sys
from pathlib import Path

def test_load_env_cli_emits_gateway_keys():
    root = Path(__file__).resolve().parents[2]
    out = subprocess.run([sys.executable, str(root / "scripts/load_env.py"), "gateway"],
                         capture_output=True, text=True, env={**os.environ, "LITEAI_ENV": "local"})
    assert out.returncode == 0, out.stderr
    emitted = dict(tok.split("=", 1) for tok in out.stdout.split())
    assert "BFF_SESSION_KEY" in emitted and "IDENTITY_ORG_URL" in emitted
```

- [ ] **Step 2: 运行,确认失败**

Run: `uv run pytest tests/config/test_loader.py::test_load_env_cli_emits_gateway_keys -q`
Expected: FAIL（`load_env.py` 不存在 → returncode≠0）

- [ ] **Step 3: 实现 `scripts/load_env.py`**

```python
#!/usr/bin/env python3
"""桥接:把 configs/<LITEAI_ENV>.yaml 摊平成某服务的 env,打印供 shell 消费。
用法:
  load_env.py <service>            # 打印 'K=V K=V'(供 `env $(load_env.py svc)`)
  load_env.py <service> --export   # 打印 'export K=V'(供 `eval`)
env 取 $LITEAI_ENV(再缺省 $ENV,再缺省 local)。"""
import os
import sys

from libs.config import export_env, load_settings, ConfigError


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: load_env.py <service> [--export]", file=sys.stderr)
        return 2
    service = argv[0]
    as_export = "--export" in argv[1:]
    env = os.environ.get("LITEAI_ENV") or os.environ.get("ENV") or "local"
    try:
        flat = export_env(load_settings(env), service)
    except ConfigError as e:
        print(f"load_env: {e}", file=sys.stderr)
        return 1
    prefix = "export " if as_export else ""
    print(" ".join(f"{prefix}{k}={v}" for k, v in flat.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

- [ ] **Step 4: 运行,确认通过**

Run: `uv run pytest tests/config/test_loader.py::test_load_env_cli_emits_gateway_keys -q`
Expected: PASS

- [ ] **Step 5: 改 `scripts/dev_services.sh` —— 删 `_env_for`,改调 `load_env.py`**

把 `scripts/dev_services.sh:18-29` 的整个 `_env_for() { ... }` 函数体替换为:
```bash
_env_for() {  # 单一源:从 configs/$LITEAI_ENV.yaml 取该服务 env(见 libs/config)
  uv run python "$ROOT/scripts/load_env.py" "$1"
}
```
并删除文件顶部第 16 行的 `JWKS=...` 默认(JWKS 现由 YAML 的 `auth.jwks_url` 提供;若其它地方仍引用 `$JWKS` 则保留)。验证 `up` 分支第 44 行 `env $(_env_for "$name")` 不变(仍消费 `K=V`)。

- [ ] **Step 6: 改 `Makefile` —— `ENV ?= local` + `run-*` 去内联**

第 13 行 `JWKS ?= ...` 上方加:
```makefile
ENV ?= local
export LITEAI_ENV = $(ENV)
LOAD = uv run python scripts/load_env.py
```
把 `run-identity`/`run-metadata`/`run-gateway`/`run-data-pipeline`(第 22-25 行)的内联 env 全部换成 `env $$($(LOAD) <svc>)`:
```makefile
run-identity:      ; env $$($(LOAD) identity) uv run uvicorn services.identity_org_service.main:app --port 8001 --reload
run-metadata:      ; env $$($(LOAD) metadata) uv run uvicorn services.metadata_service.main:app --port 8002 --reload
run-gateway:       ; env $$($(LOAD) gateway) uv run uvicorn services.gateway.main:app --port 8090 --reload
run-data-pipeline: ; env $$($(LOAD) data-pipeline) uv run uvicorn services.data_pipeline_service.main:app --port 8003 --reload
```
`up` 第 15 行去掉 `JWKS=$(JWKS)`(改 `bash scripts/dev_services.sh up`,env 由 load_env 在脚本内取)。

- [ ] **Step 7: 验证单一源(grep 证明重复已删)**

Run:
```bash
grep -n "OSS_ENDPOINT\|BFF_SESSION_KEY\|dev-web-secret" Makefile scripts/dev_services.sh
```
Expected: **无输出**(这些值现在只在 `configs/local.yaml` 一处)。

- [ ] **Step 8: 冒烟——起一个服务确认接线通**

Run:
```bash
make dev-up && sleep 8
env $(uv run python scripts/load_env.py gateway) | tr ' ' '\n' | grep -c '='   # 应为 9
make run-identity &  sleep 4; curl -fsS http://localhost:8001/healthz && echo IDENTITY_OK; kill %1
make dev-down
```
Expected: `9`;`IDENTITY_OK`。

- [ ] **Step 9: Commit**

```bash
git add scripts/load_env.py scripts/dev_services.sh Makefile tests/config/test_loader.py
git commit -m "feat(config): load_env.py 桥接 + dev_services/Makefile 走单一源(删两处重复内联)"
```

---

## Task 6: dev 持久化(Postgres 后端 + 命名卷)

> 依赖 Task 1 的 RESULTS:Postgres 凭据用本地固定值;Gravitino 卷视 P-1 结论(有目录则挂,无则跳过=缩两类)。

**Files:**
- Modify: `deploy/dev/docker-compose.yml`
- Modify: `deploy/dev/gravitino.yml`(仅当 P-1 有持久目录)

- [ ] **Step 1: 改写 `deploy/dev/docker-compose.yml`(加 Postgres + 卷 + KC 接 PG)**

```yaml
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: keycloak
      POSTGRES_USER: keycloak
      POSTGRES_PASSWORD: keycloak-dev-pw      # dev 固定值,非真密钥(§5.3)
    volumes:
      - kc-pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U keycloak -d keycloak"]
      interval: 5s
      timeout: 3s
      retries: 20
  keycloak:
    image: quay.io/keycloak/keycloak:26.6.2
    command: ["start-dev", "--import-realm", "--features=organization"]
    environment:
      KC_BOOTSTRAP_ADMIN_USERNAME: admin
      KC_BOOTSTRAP_ADMIN_PASSWORD: admin
      KC_DB: postgres
      KC_DB_URL: jdbc:postgresql://postgres:5432/keycloak
      KC_DB_USERNAME: keycloak
      KC_DB_PASSWORD: keycloak-dev-pw
    ports: ["8080:8080"]
    volumes:
      - ./keycloak:/opt/keycloak/data/import:ro
    depends_on:
      postgres:
        condition: service_healthy
  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: minio
      MINIO_ROOT_PASSWORD: minio123
    ports: ["9000:9000", "9001:9001"]
    volumes:
      - minio-data:/data
volumes:
  kc-pgdata:
  minio-data:
```

- [ ] **Step 2:(条件)给 Gravitino 加持久卷 —— 仅当 P-1 找到数据目录**

若 RESULTS 记录了 Gravitino 数据目录 `<DIR>`,改 `deploy/dev/gravitino.yml` 加:
```yaml
    volumes:
      - gravitino-data:<DIR>
networks:
  dev_default:
    external: true
    name: dev_default
volumes:
  gravitino-data:
```
(注:卷在 gravitino.yml 自己的 compose 文件声明即可;`make dev-reset` 会显式带上该文件清。)
**若 P-1 无目录:跳过此步**,在 RESULTS 注明"Gravitino 持久化 = v Next,US2 缩两类"。

- [ ] **Step 3: 实测持久化(P-2 验收 —— KC+MinIO 重启不丢)**

Run:
```bash
make dev-up && sleep 25
# 造数据:MinIO 建桶 + KC 加用户
docker run --rm --network dev_default --entrypoint sh minio/mc -c \
  "mc alias set d http://minio:9000 minio minio123 && mc mb -p d/persisttest && mc ls d/" || true
# 重启(不带 -v)
docker compose -f deploy/dev/docker-compose.yml down && sleep 3
make dev-up && sleep 25
docker run --rm --network dev_default --entrypoint sh minio/mc -c \
  "mc alias set d http://minio:9000 minio minio123 && mc ls d/ | grep persisttest && echo MINIO_PERSIST_OK"
curl -fsS http://localhost:8080/realms/lite-ai/.well-known/openid-configuration >/dev/null && echo KC_PERSIST_OK
make dev-down
```
Expected: `MINIO_PERSIST_OK` + `KC_PERSIST_OK`（重启后桶与 realm 都在）。

- [ ] **Step 4: Commit**

```bash
git add deploy/dev/docker-compose.yml deploy/dev/gravitino.yml
git commit -m "feat(dev): Keycloak 接 Postgres + MinIO/PG[/Gravitino] 命名卷(dev 持久化)"
```

---

## Task 7: dev-only 隔离 + 保数据停 vs 清空停(Makefile)

**Files:**
- Modify: `Makefile:10-17`

- [ ] **Step 1: 加 `deps-base`/`deps-dev` 语义目标 + 改停法**

把 Makefile 第 10-17 行相关目标改/加为:
```makefile
# 基础依赖(MinIO + Keycloak + Postgres)—— CI 过渡期也只需这些
deps-base:        ; docker compose -f deploy/dev/docker-compose.yml up -d
# 完整本地(基础 + dev-only:Gravitino[/swagger])—— 叠加,不可单起 overlay(external 网络依赖基础档)
deps-dev:         ; docker compose -f deploy/dev/docker-compose.yml up -d && docker compose -f deploy/dev/gravitino.yml up -d
dev-up:           ; $(MAKE) deps-dev          # 兼容旧名
# 保数据停(默认):不删卷
dev-down:         ; docker compose -f deploy/dev/gravitino.yml down; docker compose -f deploy/dev/docker-compose.yml down
# 清空停(显式毁灭性):删卷(三类数据全清)
dev-reset:        ; docker compose -f deploy/dev/gravitino.yml down -v; docker compose -f deploy/dev/docker-compose.yml down -v
```
`up`(第 15 行)改用 `deps-dev`:
```makefile
up:               ; $(MAKE) deps-dev && bash scripts/dev_services.sh up
down:             ; bash scripts/dev_services.sh down; $(MAKE) dev-down
```
`.PHONY` 行加上 `deps-base deps-dev dev-reset`。

- [ ] **Step 2: 实测两档隔离(SC-006)**

Run:
```bash
make deps-base && sleep 5
docker compose -f deploy/dev/docker-compose.yml ps --services | sort   # 应只有 keycloak minio postgres
docker ps --format '{{.Names}}' | grep -i gravitino && echo "BUG:基础档不该有 Gravitino" || echo BASE_ISOLATED_OK
make dev-down
make deps-dev && sleep 8
docker ps --format '{{.Names}}' | grep -i gravitino && echo DEV_HAS_GRAVITINO_OK
make dev-down
```
Expected: `BASE_ISOLATED_OK`（基础档无 Gravitino）+ `DEV_HAS_GRAVITINO_OK`（完整档有)。

- [ ] **Step 3: 实测保数据停 vs 清空停**

Run:
```bash
make deps-base && sleep 20
docker run --rm --network dev_default --entrypoint sh minio/mc -c \
  "mc alias set d http://minio:9000 minio minio123 && mc mb -p d/keeptest" || true
make dev-down && make deps-base && sleep 20        # 保数据停 → 再起
docker run --rm --network dev_default --entrypoint sh minio/mc -c \
  "mc alias set d http://minio:9000 minio minio123 && mc ls d/ | grep keeptest && echo KEEP_OK"
make dev-reset && make deps-base && sleep 20        # 清空停 → 再起
docker run --rm --network dev_default --entrypoint sh minio/mc -c \
  "mc alias set d http://minio:9000 minio minio123 && (mc ls d/ | grep keeptest && echo RESET_FAIL || echo RESET_OK)"
make dev-reset
```
Expected: `KEEP_OK`(保数据停后桶还在)+ `RESET_OK`(清空停后桶没了)。

- [ ] **Step 4: Commit**

```bash
git add Makefile
git commit -m "feat(dev): deps-base/deps-dev 隔离 + dev-down(保数据)/dev-reset(清空)"
```

---

## Task 8: 全绿门禁 + owner-readable 验收 runbook

**Files:**
- Modify: 计划本文件(嵌入 runbook)

- [ ] **Step 1: 跑全绿门禁(SC-007)**

Run:
```bash
make gen && make lint && uv run pytest -q
```
Expected: 全 PASS;`lint-imports` 通过(确认 `libs/config` 在 libs 底层、无反向依赖)。失败走 `superpowers:systematic-debugging`,不假绿。

- [ ] **Step 2: 验串味消失(SC-001)—— 自动核对所有服务存储端点同源本地**

Run:
```bash
for svc in identity metadata data-pipeline gateway; do
  echo "== $svc =="; uv run python scripts/load_env.py $svc | tr ' ' '\n' | grep -iE 'OSS_ENDPOINT|aliyuncs' || echo "(无 OSS)"
done
uv run python scripts/load_env.py data-pipeline | grep -q "OSS_ENDPOINT=http://localhost:9000" && echo NO_DRIFT_OK
uv run python -c "from libs.config import load_settings; s=load_settings('local'); assert 'aliyuncs' not in s.oss.endpoint; print('LOCAL_NO_CLOUD_OK')"
```
Expected: 所有 OSS_ENDPOINT 均 `http://localhost:9000`;`NO_DRIFT_OK` + `LOCAL_NO_CLOUD_OK`。

- [ ] **Step 3: 验 test 档 fail-fast(SC-005,单测层)**

Run:
```bash
env -u OSS_SECRET_KEY -u OSS_ACCESS_KEY -u BFF_SESSION_KEY -u OIDC_CLIENT_SECRET \
  uv run python -c "from libs.config import load_settings,ConfigError;
try:
  load_settings('test'); print('FAIL: 应报错')
except ConfigError as e:
  print('FAILFAST_OK:', e)"
```
Expected: `FAILFAST_OK: [test] 必需配置占位未注入: ...`

- [ ] **Step 4: 写 owner-readable runbook 到本计划末尾(见下「## 手动验收 Runbook」),并提交**

```bash
git add docs/superpowers/plans/2026-06-23-env-config-persistence.md
git commit -m "docs(plan): env-config 手动验收 runbook(owner-readable)"
```

---

## 手动验收 Runbook(owner 逐步跑,白话)

> 宪法 §3.4 / ADR-015:每步说「跑什么命令 / 应看到什么」,无术语。在仓库根目录、终端里逐条复制运行。

### 准备
- [ ] **1. 确认 Docker 在跑**
  - 跑:`docker ps`
  - 应看到:列出一个表格(可能为空),**不报错**。报错就先打开 Docker Desktop。

### 验收一:开发环境完全本地、绝不连云(最重要)
- [ ] **2. 起全部本地服务**
  - 跑:`make up`
  - 应看到:几行 `xxx → :端口`,最后一行 `入口:gateway http://localhost:8090`。等约 30 秒让它们起好。
- [ ] **3. 检查每个服务连的存储都是本地**
  - 跑:`for s in identity metadata data-pipeline gateway; do echo "== $s =="; uv run python scripts/load_env.py $s | tr ' ' '\n' | grep -i oss_endpoint || echo "(此服务不连存储)"; done`
  - 应看到:凡出现存储地址的,**全都是 `http://localhost:9000`**;**绝不能出现 `aliyuncs.com`**。看到 aliyuncs 就是没修好,停下找我。
- [ ] **4. 停掉**
  - 跑:`make down`
  - 应看到:几行"停 xxx",无报错。

### 验收二:开发数据重启不丢
- [ ] **5. 起基础依赖并造一份数据**
  - 跑:`make deps-base`(等约 25 秒)
  - 跑:`docker run --rm --network dev_default --entrypoint sh minio/mc -c "mc alias set d http://minio:9000 minio minio123 && mc mb -p d/我的测试桶 && mc ls d/"`
  - 应看到:列出 `我的测试桶`。
- [ ] **6. 重启(用"保数据"的停法)**
  - 跑:`make dev-down`(这是保数据停,不会删)
  - 跑:`make deps-base`(等约 25 秒)
- [ ] **7. 确认数据还在**
  - 跑:`docker run --rm --network dev_default --entrypoint sh minio/mc -c "mc alias set d http://minio:9000 minio minio123 && mc ls d/"`
  - 应看到:`我的测试桶` **仍然在**。在 = 持久化成功 ✅。不在 = 没修好,找我。
- [ ] **8. 确认登录用户也持久(Keycloak)**
  - 跑:`curl -s http://localhost:8080/realms/lite-ai/.well-known/openid-configuration | head -c 60; echo`
  - 应看到:一段以 `{"issuer"` 开头的 JSON(说明重启后 realm 还在)。

### 验收三:确实想清空时能清
- [ ] **9. 清空停**
  - 跑:`make dev-reset`(这是毁灭性清空)
  - 跑:`make deps-base`(等约 25 秒)
  - 跑:`docker run --rm --network dev_default --entrypoint sh minio/mc -c "mc alias set d http://minio:9000 minio minio123 && mc ls d/"`
  - 应看到:**空的**(我的测试桶没了)= 清空生效 ✅。

### 验收四:dev-only 服务隔离
- [ ] **10. 基础档不该带 Gravitino**
  - 跑:`make dev-down; make deps-base; sleep 5; docker ps --format '{{.Names}}'`
  - 应看到:有 minio/keycloak/postgres,**没有** gravitino。
- [ ] **11. 完整档才带 Gravitino**
  - 跑:`make dev-down; make deps-dev; sleep 8; docker ps --format '{{.Names}}'`
  - 应看到:这次**有** gravitino 了。
- [ ] **12. 收尾清理**
  - 跑:`make dev-reset`
  - 应看到:几行 down,无报错。

> 注:若探针 P-1 结论为"Gravitino 1.1.0 无持久目录",验收二只覆盖 MinIO + Keycloak 两类(第 7、8 步),Gravitino 持久化留作后续——这是事先约定好的分支。

---

## Self-Review(写完对照 spec)

- **FR-001/002/003/004**(单一源/单开关/去重/同环境)→ Task 3(configs)+ Task 5(load_env + 删两处重复 + grep 证明)+ Task 2(load_settings 单 env)。✅
- **FR-005**(持久 + 显式清空)→ Task 6(卷)+ Task 7(dev-down 保 / dev-reset 清)。✅
- **FR-006**(两档启动)→ Task 7(deps-base/deps-dev)。✅
- **FR-007**(密钥不入库 + 非本地 fail-fast)→ Task 2(${VAR} + ConfigError)+ Task 3(test/prod 占位)。✅
- **FR-008**(不破 CI + 不改读法)→ 桥接保 os.environ(Task 4/5);CI 未改;门禁 Task 8。✅
- **FR-009**(test/prod 骨架显式 TBD)→ Task 3。✅
- **SC-001**→Task 8 Step2;**SC-002**→Task 6 Step3 + runbook 验收二;**SC-003**→ENV 单开关 Task 5;**SC-004**→Task 5 Step7 grep;**SC-005**→Task 8 Step3;**SC-006**→Task 7 Step2;**SC-007**→Task 8 Step1;**SC-008**(worker 继承)→Task 4 不变量测试 + runbook 可选真作业。✅
- **US2 缩两类分支**:Task 1 决策规则 + Task 6 Step2 条件 + runbook 注。✅
- **探针**:P-1/P-2/P-3 → Task 1。✅
- Placeholder 扫描:无 TBD/TODO 残留(configs 内的 `# TBD` 是 spec FR-009 要求的**显式**占位,非计划缺口)。✅
- 类型一致:`load_settings`/`export_env`/`SERVICE_ENV_KEYS`/`ConfigError`/`Settings` 跨 Task 2/4/5 命名一致。✅
