# Spike RESULTS — 探针 P-1 / P-2 / P-3(持久化落盘事实)

Plan: `2026-06-23-env-config-persistence` · Task 1(PROBE/SPIKE,非 TDD)
执行日期:2026-06-23 · 全程本地 Docker · 仅产出本文件,未写任何生产代码。

> 目的:为 Task 6 (dev 持久化) 确定三个 dev 依赖各自需要挂哪个卷 / 挂到哪个目录。
> 结论是**真实命令输出的观测事实**,非推测。

---

## 实际使用的镜像 tag

| 依赖 | 镜像 tag | 备注 |
|------|----------|------|
| Gravitino (P-1) | `apache/gravitino:1.1.0` | 计划指定 tag 可用,无需降级 |
| Keycloak (P-2)  | `quay.io/keycloak/keycloak:26.6.2` | 取自 `deploy/test/docker-compose.yml` 模板 |
| Postgres (P-2)  | `postgres:16-alpine` | KC 后端;arm64 host 拉 amd64 镜像有 platform warning(可忽略,正常运行) |
| MinIO (P-3)     | `minio/minio:latest` → `RELEASE.2025-09-07T16-13-09Z` | latest 解析到该 release |

---

## 端口冲突处理(环境前置事实)

探针开始时,本机已有上一轮会话遗留的 `dev` compose 栈在跑,占用了探针要用的全部端口:

```
dev-gravitino-1   apache/gravitino:1.1.0             0.0.0.0:8091->8090/tcp
dev-keycloak-1    quay.io/keycloak/keycloak:26.6.2   0.0.0.0:8080->8080/tcp
dev-minio-1       minio/minio:latest                 0.0.0.0:9000-9001->9000-9001/tcp
dev-swagger-ui-1  swaggerapi/swagger-ui:latest       0.0.0.0:8088->8080/tcp
```

处理:
- **P-1** 直接 inspect 已在跑的 `dev-gravitino-1`(同为 `apache/gravitino:1.1.0`,事实等价),省去再起 probe-grav。
- **P-2 / P-3** 需要 8080 / 9000:用 `docker compose -p dev ... stop`(不带 `-v`,保数据)临时停掉 dev 栈腾端口;探针跑完后用 `... start` **原样恢复**。已确认恢复后四个 dev 容器全部 Up。

---

## P-2 — Keycloak-on-Postgres dev 可行性 ✅ 可行

模板:`deploy/test/docker-compose.yml`(Postgres + Keycloak,卷 `kc-pgdata:/var/lib/postgresql/data`)。

**踩坑(必须记录,直接影响 Task 6/Task 7):**
首次 `up` 时 Keycloak 报:

```
ERROR: Failed to obtain JDBC connection
ERROR: FATAL: password authentication failed for user "keycloak"
```

根因:`test_kc-pgdata` 卷是 **2026-06-09 上一轮探针**留下的(`docker volume inspect` CreatedAt = `2026-06-09T11:42:47Z`)。Postgres **只在首次初始化数据目录时**写入 `POSTGRES_PASSWORD`;卷已存在 → 新传的 `KC_DB_PASSWORD=devpw` 对 Postgres 无效,而 Keycloak 拿的是 `devpw`,两边密码不一致 → 认证失败。
解决:`down -v` 清掉陈旧卷后重新 `up`,即成功。

> ⚠️ Task 6/Task 7 启示:Postgres 命名卷一旦初始化,**改密码必须连卷一起 reset**(`dev-reset` 语义);否则改 `.env` 里的 DB 密码不会生效,且会静默挂掉 Keycloak。

清卷重起后:

```
NAME              IMAGE                              STATUS
test-keycloak-1   quay.io/keycloak/keycloak:26.6.2   Up 38 seconds
test-postgres-1   postgres:16-alpine                 Up 43 seconds (healthy)

REALM_OK after ~25s
issuer: http://localhost:8080/realms/lite-ai
token_endpoint: http://localhost:8080/realms/lite-ai/protocol/openid-connect/token
```

`--import-realm` 成功导入 `lite-ai` realm,OIDC discovery 端点 200。探针结束 `down`(不带 `-v`,留卷),`deploy/test` 栈现已 down。

**结论:KC-on-Postgres dev 可行 ✅。** 持久卷 = `kc-pgdata:/var/lib/postgresql/data`(Postgres 数据目录,realm/用户落在这里)。

---

## P-3 — MinIO 命名卷 `:/data` ✅ 可行,无子挂载冲突

```bash
docker run -d --name probe-minio -p 9000:9000 -v probe-minio-data:/data \
  -e MINIO_ROOT_USER=minio -e MINIO_ROOT_PASSWORD=minio123 minio/minio:latest server /data
```

容器内 `/data` 观测:

```
total 12
drwxr-xr-x 3 root root 4096 Jun 23 01:45 .
drwxr-xr-x 7 root root 4096 Jun 23 01:45 .minio.sys     # MinIO 在卷根初始化,无嵌套挂载冲突
-rw-r--r-- 1 root root 0 Jun 23 01:46 /data/.probe       # 写入成功
MINIO_VOL_OK
```

**持久性二次验证:** 删容器、用同一命名卷重起,`/data/.probe` 仍在:

```
-rw-r--r-- 1 root root 0 Jun 23 01:46 /data/.probe
MINIO_PERSIST_OK
```

**结论:MinIO `minio-data:/data` 命名卷可行 ✅。** `.minio.sys` 落在卷根,数据跨容器重建保留,无子挂载冲突。探针容器 + 卷已清理(`docker rm -f probe-minio` + `docker volume rm probe-minio-data`)。

---

## P-1 — Gravitino 1.1.0 元数据落盘位置(本探针真正的未知项)✅ 找到独立持久目录

镜像内工作目录 `pwd = /root/gravitino`。配置 `/root/gravitino/conf/gravitino.conf`:

```
gravitino.entity.store              = relational
gravitino.entity.store.relational   = JDBCBackend
gravitino.entity.store.relational.jdbcUrl    = jdbc:h2
gravitino.entity.store.relational.jdbcDriver = org.h2.Driver
gravitino.entity.store.relational.jdbcUser   = gravitino
gravitino.entity.store.relational.jdbcPassword = gravitino
```

即 1.1.0 默认 **relational / JDBCBackend / 内嵌 H2**(非 in-memory、非 RocksDB)。H2 数据库文件实际落盘在 `./data`(= `/root/gravitino/data`):

```
$ ls -la /root/gravitino/data
-rw-r--r-- 1 root root   146 Jun 23 00:30 jdbc.lock.db
-rw-r--r-- 1 root root 61440 Jun 23 00:30 jdbc.mv.db      # H2 MVStore 主数据文件
```

`./data` 与 `/root/gravitino/data` 列出内容完全一致(相对路径 = 该绝对路径)。fileset catalog 的元数据(catalog/schema/fileset 实体)随 entity store 一并存在这套 H2 文件里。

> 注:被探针对象未挂任何卷(`docker inspect dev-gravitino-1` → `Mounts: []`),所以当前 dev Gravitino 的元数据是**易失的**(重建即丢)——这正是 Task 6 要修的。

**P-1 结论:有独立持久目录 → `<DIR> = /root/gravitino/data`。** 不触发"缩两类"分支。

---

## Task 6 应该怎么做(推荐)

按 decision rule,三类依赖**全部**纳入 dev 持久化(不缩):

| 依赖 | 挂载(命名卷 → 容器内目录) | 说明 |
|------|------------------------------|------|
| **Gravitino** | `gravitino-data:/root/gravitino/data` | H2 entity store(`jdbc.mv.db`),含 fileset catalog 元数据 |
| **Keycloak**(经 Postgres) | `kc-pgdata:/var/lib/postgresql/data` | KC 后端从 dev 内置 H2 换 Postgres(模板已验证);realm/用户落 PG 数据目录 |
| **MinIO** | `minio-data:/data` | 对象数据 + `.minio.sys`,卷根直挂无冲突 |

约束(来自 plan + 本探针):
1. 三个命名卷都必须属于 compose project **`dev`**,使 `down`(不带 `-v`)保数据、`dev-reset`(带 `-v`)清空。
2. **Postgres 密码与卷强绑定**:改 `.env` 里 DB 密码必须连 `kc-pgdata` 一起 reset,否则 Postgres 沿用旧密码、Keycloak 静默挂掉(见 P-2 踩坑)。`dev-reset` 须真正 `down -v`。
3. Gravitino 切到持久卷后,1.1.0 默认 H2 即可满足 dev(无需上 Postgres 后端);如未来要多实例/并发再议 vNext。
4. arm64 host 拉 `postgres:16-alpine` 有 platform(amd64)warning,功能正常,Task 6 可忽略或显式 `platform: linux/amd64`。

---

## 清理与终态确认

- `probe-minio` 容器 + `probe-minio-data` 卷:已删。
- `deploy/test` compose:已 `down`(无 test-keycloak / test-postgres 残留)。
- 未起 `probe-grav`(改用已在跑的 `dev-gravitino-1` inspect,事实等价)。
- 临时停掉的用户 `dev` 栈:已 `start` 原样恢复,四容器(gravitino/keycloak/minio/swagger-ui)全部 Up。
- `docker ps -a | grep -E 'probe-|test-keycloak|test-postgres'` → `NONE`。
