# Keycloak Organizations 作企业 + 注册/邀请;v1 移除用户组层 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development(推荐)或 superpowers:executing-plans 逐 task 实现。步骤用 checkbox(`- [ ]`)跟踪。

**Goal:** 把「企业」从 KC realm group 路径约定升级为 **KC Organization**(不透明 alias 作 enterprise_id),身份降两级(平台→企业→用户)、`group_id` 全面清理,并打通**自助注册按邮箱域自动归企业 + 邀请**;企业硬隔离与 owner 授权不回归。

**Architecture:** 唯一改变点 = token 的 `organization` claim(KC Organization Membership mapper,**已实测**=org alias 数组,默认进 access token)→ `libs/identity/context.py:parse_context` 读它产出 `Membership(enterprise_id=alias, role)`(去 group_id)→ 下游 `can()`/Gravitino/OSS 隔离判定零改(can() 实测不读 group_id)。BFF 认证请求带 `scope=organization:*`(规避多-org claim 消失坑)。enterprise_id 改不透明 alias → 契约 pattern/Gravitino metalake/OSS 前缀一致换值(v1 prod 无数据=清晰切换,dev 重建)。

**Tech Stack:** Keycloak 26.6.2(`--features=organization`)、FastAPI、httpx、Gravitino、boto3/OSS、React/Vite+vitest、pytest、mailpit(dev SMTP)、datamodel-codegen/openapi-typescript。

**地基:** [ADR-025](../adr/ADR-025-keycloak-organizations-as-enterprise.md)(Accepted)+ [探针 RESULTS](./2026-06-24-kc-organizations-enterprise/spikes/RESULTS.md)(KC 26.6.2 实测)。spec/design:[`2026-06-24-kc-organizations-enterprise/`](./2026-06-24-kc-organizations-enterprise/)(已过 DoR)。
**分支:** 从 `main` 拉 `kc-organizations-enterprise`。
**宪法同步:** 本计划**与代码同批**改 `docs/constitution.md` §1.1/1.2/1.3/1.4/1.6/2.1/2.2/5.1/8 + `CLAUDE.md`(ADR-025 §0 硬纪律;Task 8),保持宪法 ≡ 实现。

---

## File Structure
| 文件 | 责任 | 动作 |
|---|---|---|
| `deploy/dev/keycloak/realm-lite-ai.json` | dev realm:org(不透明 alias)+ 注册 + organization scope + mailpit SMTP | 改 |
| `scripts/provision_orgs.py`(新)| 幂等迁移/置备:建 org、存量用户 unmanaged 加入、配 mapper/scope、移除旧 g- 子组 | 建 |
| `deploy/dev/docker-compose.yml` | 加 `mailpit`(dev SMTP,验注册/邀请邮件)| 改 |
| `libs/identity/context.py` | `parse_context` 读 organization claim;`Membership` 去 group_id;`role_in` 去 gid | 改 |
| `libs/identity/ids.py` | 删 `GroupId` | 改 |
| `services/_scaffold/auth.py` | `context_from_request` 透传 organization claim(+ 测试 seam)| 改 |
| `services/gateway/bff/oidc.py` | authorize scope = `openid organization:*` | 改 |
| `services/gateway/bff/middleware.py` | `/auth/me` 解 organization + 企业 display_name | 改 |
| `libs/authz/types.py` | `Resource` 删 group_id | 改 |
| `libs/audit/oss_audit.py` | `AuditEvent` 删 group_id | 改 |
| `services/data_pipeline_service/app.py` | 删 `_caller_group`;`role_in`/audit 去 group | 改 |
| `services/identity_org_service/app.py` | `/v1/me/orgs` 去 group_id、加 organization/display_name | 改 |
| `pipelines/data_prep/runner.py` | `role_in` 调用去 gid | 改 |
| `contracts/openapi/{identity-org,metadata,data-pipeline}.yaml` | enterprise_id pattern 放宽;identity-org 去 group_id/^g- + 加 display_name | 改 |
| `services/metadata_service/app.py` + `scripts/bootstrap_catalog.py` | metalake = `alias.replace("-","_")`(沿用),按不透明 alias bootstrap | 验/小改 |
| BFF 邀请端点(gateway)| `POST /auth/orgs/invite`(can=enterprise-admin)→ KC org 邀请 API | 建 |
| `frontend/src/pages/Account.tsx` + 邀请 UI | 显示企业 display_name;enterprise-admin 邀请入口 | 改 |
| `docs/constitution.md` + `CLAUDE.md` | §1.x/2.x/5.1/8 同步(ADR-025 草案)| 改 |
| `scripts/ci_guards.sh` | grep 去 group_id 比较项 | 改 |

---

## Task 1: KC realm — Organizations + 注册 + organization:* scope(置备)

**Files:** Modify `deploy/dev/keycloak/realm-lite-ai.json`、`deploy/dev/docker-compose.yml`;Create `scripts/provision_orgs.py`;Test `tests/identity/test_provision_orgs.py`(对 KC admin client 的单元/契约级)。

> 探针 RESULTS 已实测机制;本 task 把它落到 lite-ai dev realm + 幂等置备脚本(供 prod/重导)。

- [x] **Step 1: realm JSON 开 organizations + 注册 + mailpit SMTP**
  `realm-lite-ai.json` 顶层加 `"organizationsEnabled": true`、`"registrationAllowed": true`、`"registrationEmailAsUsername": true`、`"smtpServer": {"host":"mailpit","port":"1025","from":"noreply@lite-ai.dev"}`;新增一个 org 节点:`"organizations":[{"name":"Demo","alias":"ent-demo","domains":[{"name":"acme.test","verified":true}],"redirectUrl":"","attributes":{"display_name":["Demo 企业"]}}]`(alias 不透明、不复用 e-XXXX);把 `organization` client scope 加到 `lite-ai-web`/`gateway` client 的 `defaultClientScopes`。
  - 注:realm import 不一定建 org 成员关系 → 成员由 Step 3 脚本补。

- [x] **Step 2: docker-compose 加 mailpit**
  `deploy/dev/docker-compose.yml` 加服务:`mailpit: { image: axllent/mailpit, ports: ["8025:8025","1025:1025"] }`(8025 web UI 看邮件,1025 SMTP)。

- [x] **Step 3: 写 `scripts/provision_orgs.py`(幂等)**
  用 KC admin REST(admin/admin,master/admin-cli):① 建/取 org(by alias `ent-demo`,设 domains + display_name attribute);② 把现有 realm 用户(alice 等,by username)以 **unmanaged** `POST organizations/{id}/members`(已是成员则跳);③ 确认 `organization` mapper `access.token.claim=true`、`multivalued=true`;④ 把 `organization` scope 设为 client default scope;⑤ **移除旧 `/e-XXXX/g-YYYY/` 子组**(by group path,存在才删)。每步查重幂等。

- [x] **Step 4: 契约级测试**
  `tests/identity/test_provision_orgs.py`:mock KC admin httpx,断言脚本对"org 已存在/成员已存在"幂等(不重复 POST)、对缺失则建。

- [~] **Step 5: 真机验证 token(owner runbook 也覆盖)** — 延后到 owner runbook §1。
  需 `make dev-reset && make deps-dev` 重导 realm(realm 级 `organizationsEnabled` 才生效),该操作会清空本机 KC/MinIO 卷(毁灭性),headless 不擅自执行;置备逻辑已由 `tests/identity/test_provision_orgs.py` 契约级幂等测试锁定。
  Expected:claim 带不透明 alias;无选择器多-org 才为 null(单 org 用户不受影响)。

- [x] **Step 6: Commit** `git add -A && git commit -m "feat(kc): realm Organizations + 注册 + mailpit + 幂等 provision_orgs 脚本"`

---

## Task 2: parse_context seam — 读 organization claim,Membership 去 group_id

**Files:** Modify `libs/identity/context.py`、`libs/identity/ids.py`;Test `tests/identity/test_context.py`。

- [x] **Step 1: 改红测试**
  `tests/identity/test_context.py` 改/加:
  ```python
  from libs.identity.context import parse_context, Membership
  def test_parse_org_claim_single():
      ctx = parse_context(sub="u-1", organization=["ent-demo"], realm_roles=[])
      assert ctx.memberships == [Membership(enterprise_id="ent-demo", role="member")]
      assert not hasattr(ctx.memberships[0], "group_id")  # group 维度已删
  def test_parse_enterprise_admin_role():
      ctx = parse_context(sub="u-1", organization=["ent-demo"], realm_roles=["enterprise-admin"])
      assert ctx.memberships[0].role == "enterprise-admin"
  def test_parse_platform_admin():
      ctx = parse_context(sub="u-1", organization=[], realm_roles=["platform-admin"])
      assert ctx.is_platform_admin and ctx.memberships == []
  def test_role_in_no_group_arg():
      ctx = parse_context(sub="u-1", organization=["ent-demo"], realm_roles=["enterprise-admin"])
      assert ctx.role_in("ent-demo") == "enterprise-admin"
  ```
- [x] **Step 2: 跑红** `uv run pytest tests/identity/test_context.py -q` → FAIL(签名/字段不符)。
- [x] **Step 3: 实现**
  `libs/identity/context.py`:
  ```python
  @dataclass(frozen=True)
  class Membership:
      enterprise_id: EnterpriseId
      role: str  # member | enterprise-admin

  @dataclass(frozen=True)
  class Context:
      user: str
      memberships: list[Membership] = field(default_factory=list)
      is_platform_admin: bool = False
      def role_in(self, enterprise_id: EnterpriseId) -> str | None:
          best = None
          for m in self.memberships:
              if m.enterprise_id != enterprise_id: continue
              best = "enterprise-admin" if m.role == "enterprise-admin" else (best or m.role)
          return best

  _PLATFORM_ROLE = "platform-admin"
  _ENT_ADMIN_ROLE = "enterprise-admin"
  def parse_context(sub: str, organization: list[str], realm_roles: list[str]) -> Context:
      is_platform = _PLATFORM_ROLE in (realm_roles or [])
      role = _ENT_ADMIN_ROLE if _ENT_ADMIN_ROLE in (realm_roles or []) else "member"
      memberships = [Membership(EnterpriseId(a), role) for a in (organization or [])]
      return Context(user=sub, memberships=memberships, is_platform_admin=is_platform)
  ```
  `libs/identity/ids.py`:删 `GroupId`(只留 `EnterpriseId`)。
  > 注:role 暂用 realm role 全局判(v1 单企业够用;多企业 per-org 角色 = v-next)。删除旧 `_RE_GROUP`/`_RE_ENT_ADMIN`/`_PLATFORM` group 路径正则。
- [x] **Step 4: 跑绿** `uv run pytest tests/identity/test_context.py -q` → PASS.
- [x] **Step 5: Commit** `git commit -am "feat(identity): parse_context 读 organization claim;Membership 去 group_id;role_in 去 gid"`

---

## Task 3: context_from_request + BFF — 透传 organization claim + organization:* scope

**Files:** Modify `services/_scaffold/auth.py`、`services/gateway/bff/oidc.py`、`services/gateway/bff/middleware.py`;Test `tests/services/scaffold/test_auth.py`、`tests/gateway/bff/test_session_mw.py`、`tests/gateway/bff/test_oidc.py`。

- [x] **Step 1: 改红测试(scaffold auth)**
  `tests/services/scaffold/test_auth.py`:x-test-claims seam 带 `{"sub","organization":["ent-demo"],"realm_roles":["enterprise-admin"]}` → `context_from_request` 产出 `role_in("ent-demo")=="enterprise-admin"`;真 JWT 路径 mock `verify_and_decode` 返回含 `organization`/`realm_access.roles` → 同。
- [x] **Step 2: 实现 `context_from_request`**
  改 `services/_scaffold/auth.py`:解出 `organization = claims.get("organization", [])`(KC `multivalued=true` 为 list;若为 str 包成 list)、`realm_roles = claims.get("realm_access",{}).get("roles",[])`;`return parse_context(sub=claims["sub"], organization=organization, realm_roles=realm_roles)`。x-test-claims 同形态。`enterprise_of` 不变(0/多企业显式拒)。
- [x] **Step 3: BFF authorize 带 organization:\* scope**
  `services/gateway/bff/oidc.py:authorize_url`:`"scope": "openid organization:*"`(规避多-org claim 消失,RESULTS F3)。token 交换沿用。
- [x] **Step 4: `/auth/me` 加 organization + 企业 display_name**
  `services/gateway/bff/middleware.py:auth_me`:从 claims 取 `organization`,返回 `enterprises`(alias 列表)+ 若 token 带 org display_name attribute 则带出(否则 alias);沿用 F2 在 access token。
- [x] **Step 5: 跑绿** `uv run pytest tests/services/scaffold tests/gateway/bff -q` → PASS。
- [x] **Step 6: Commit** `git commit -am "feat(bff): context_from_request 透传 organization;authorize 带 organization:* scope;/auth/me 加企业"`

---

## Task 4: group_id 全面清理 — Resource/audit/_caller_group/role_in 调用点/me_orgs

**Files:** Modify `libs/authz/types.py`、`libs/audit/oss_audit.py`、`services/data_pipeline_service/app.py`、`services/identity_org_service/app.py`、`pipelines/data_prep/runner.py`;Test 相应。

- [x] **Step 1: 改红测试**
  - `tests/services/data_pipeline/test_app.py`/`test_resolve.py`:审计断言去 `group_id`;`role_in(EnterpriseId(ent))` 单参。
  - `tests/services/identity/test_me_orgs.py`(或现有):`/v1/me/orgs` 返回项**无 `group_id`**、含 `enterprise_id`/`role`。
  - authz `tests/authz/test_can.py`:`Resource(...)` 构造去 `group_id`。
- [x] **Step 2: 实现清理**
  - `libs/authz/types.py`:`Resource` 删 `group_id` 字段。
  - `libs/audit/oss_audit.py`:`AuditEvent` 删 `group_id` 字段。
  - `services/data_pipeline_service/app.py`:**删 `_caller_group`**;`_audit` 去 `group_id=` 实参;所有 `role_in(EnterpriseId(ent))` 保持单参(已是);所有 `Resource(... group_id=None ...)` 去该参。
  - `services/identity_org_service/app.py:me_orgs`:投影去 `group_id`。
  - `pipelines/data_prep/runner.py`:`role_in` 调用去 gid 实参(若有)。
- [x] **Step 3: 跑绿** `uv run pytest -q` 全套(期望全绿;若个别测试仍引用 group_id 一并改)。
- [x] **Step 4: lint** `uv run lint-imports`(layering KEPT)。
- [x] **Step 5: Commit** `git commit -am "refactor(authz/audit): 全面清理 group_id(Resource/AuditEvent/_caller_group/me_orgs)"`

---

## Task 5: 契约 — enterprise_id pattern 放宽 + identity-org 去 group_id 加 organization/display_name

**Files:** Modify `contracts/openapi/{identity-org,metadata,data-pipeline}.yaml`;regen `libs/contracts_gen/*` + `frontend/src/api/types-*.ts`;Test `tests/contracts/*`(若有)。

- [x] **Step 1: 改契约**
  - 三契约 `enterprise_id` pattern `^e-[0-9a-z]+$` → **`^[a-z][a-z0-9-]{3,}$`**(容不透明 alias,4 处)。
  - `identity-org.yaml`:`Membership` 删 `group_id`/`^g-` pattern;`/v1/me/orgs` 响应加 `enterprises`(alias[])+ 每企业 `display_name`(可空)。
- [x] **Step 2: 重生成 + 校验确定性**
  Run:`make gen && git diff --stat libs/contracts_gen/`(应只反映本次契约改动)+ `make fe-types`。
- [x] **Step 3: 跑绿** `uv run pytest -q`(契约模型变更后服务/测试仍绿)。
- [x] **Step 4: Commit** `git commit -am "contract: enterprise_id pattern 放宽容不透明 alias;identity-org 去 group_id + 加 organization/display_name;regen"`

---

## Task 6: enterprise_id 不透明 alias 下游 — Gravitino metalake / OSS / bootstrap

**Files:** Verify/Modify `services/metadata_service/app.py`(`_metalake`)、`pipelines/data_prep/paths.py`、`scripts/bootstrap_catalog.py`;Test `tests/services/metadata/*`、`tests/pipelines/test_paths.py`。

- [x] **Step 1: 确认 `_metalake` 对不透明 alias 合法**
  `_metalake(ent) = ent.replace("-","_")`;alias `ent-demo` → `ent_demo`(合法 `[a-z0-9_]`)。`tests/services/metadata/...` 加 `_metalake("ent-demo")=="ent_demo"` 断言。
- [x] **Step 2: paths/契约 pattern 一致**
  `tests/pipelines/test_paths.py`:`DatasetPaths(bucket,"ent-demo",user,ds).raw_prefix` == `ent-demo/{user}/raw/{ds}/`(企业段为不透明 alias)。`DatasetPaths` 无需改(纯字符串);确认 dataset/filename 校验不误伤 alias。
- [x] **Step 3: bootstrap 接受不透明 alias**
  `scripts/bootstrap_catalog.py`:`main(eid)` 的 `eid` 现可为 `ent-demo`;metalake=`ent_demo`。Run:`make bootstrap-catalog EID=ent-demo` → `bootstrapped ent_demo/data/datasets`。
- [x] **Step 4: 跑绿** `uv run pytest tests/services/metadata tests/pipelines -q` → PASS。
- [x] **Step 5: Commit** `git commit -am "feat(tenancy): Gravitino metalake/OSS 按不透明 alias;bootstrap 接受 alias"`

---

## Task 7: 注册按邮箱域自动归属 + 邀请 — BFF 端点 + e2e

**Files:** Create BFF 邀请路由(`services/gateway/bff/orgs.py` 或并入 routes)+ KC admin 客户端;Test `tests/gateway/bff/test_orgs_invite.py`;e2e 用 mailpit。

- [x] **Step 1: 邀请端点(改红)**
  `tests/gateway/bff/test_orgs_invite.py`:`POST /auth/orgs/invite`(body `{email}`)→ 仅 `enterprise-admin`(会话角色)可调;mock KC admin httpx,断言转发到 `organizations/{id}/members/invite-user`;非 admin → 403;无 CSRF → 403。
- [x] **Step 2: 实现邀请端点**
  BFF 新路由 `POST /auth/orgs/invite`(`services/gateway/bff/orgs.py` OrgInviter + middleware install_bff 路由):会话取 caller 的 org(alias)+ 角色 → enterprise-admin 才放行 → KC admin client(admin 凭据 env 注入,§5.2)调 `invite-user`。CSRF 由会话中间件强制(变更方法非豁免)。
- [~] **Step 3: 注册自动归属 e2e(手动 runbook 钉死)** — 延后到 owner runbook §3(需 live KC + 浏览器,headless 不可跑;机制已就位:realm registrationAllowed + org domains acme.test + mailpit)。
- [~] **Step 4: 邀请 e2e** — 延后到 owner runbook §4(需 live KC + mailpit;端点/inviter 已契约级测试锁定)。
- [x] **Step 5: 跑绿 + Commit** `uv run pytest tests/gateway/bff/test_orgs_invite.py -q` → PASS。

---

## Task 8: 宪法同步 + CI guard(随实现同批落,ADR-025 §0)

**Files:** Modify `docs/constitution.md`、`CLAUDE.md`、`scripts/ci_guards.sh`。

- [x] **Step 1: 改宪法本体(照 ADR-025 草案)**
  `docs/constitution.md`:§1.1 四级→两级(平台/企业/用户,删"用户组");§1.2 删 `GroupId`;§1.3 `enterprise_id=不透明 org alias`、删 `group_id=g-XXXX`;§1.4 删"私有资源还须 group_id";§1.6 私有资源按 owner(删 group_id 匹配,衔接 ADR-024);§2.1 `Organizations(企业,不透明 alias)+ 注册/邀请;删 Group 子组`;§2.2 `角色=member/enterprise-admin,经 realm role/org 属性表达,随 organization claim;不再 group 路径编码`;§5.1 审计 label 删 `group_id`;§8 grep 项删 `group_id`。
- [x] **Step 2: 改 CLAUDE.md 引言指针**
  "多企业租户与标识"指针更新为:企业=Organization 不透明 alias、两级、group→Cerbos。
- [x] **Step 3: ci_guards 去 group_id**
  `scripts/ci_guards.sh`:删/改 `group_id` 散落比较 grep 项。Run `bash scripts/ci_guards.sh` → 绿。
- [x] **Step 4: Commit** `git commit -am "docs(constitution): 同步 ADR-025(企业=org 不透明 alias、两级、删 group 维度)+ CLAUDE.md + ci_guards"`

---

## Task 9: 前端 — 账户页企业 display_name + 邀请 UI

**Files:** Modify `frontend/src/pages/Account.tsx`、`frontend/src/auth/useOrgs.ts`/`useMe.ts`;Create 邀请 UI(账户页或独立);regen types;Test vitest。

- [x] **Step 1: 改红 vitest**
  `Account.test.tsx`:mock `/v1/me/orgs` 返回 `{enterprises:[{alias:"ent-demo",display_name:"Demo 企业"}], ...}`(无 group_id)→ 断言页面显示 **"Demo 企业"**(非 alias、非 UUID);角色显示 member/enterprise-admin。
- [x] **Step 2: 实现**
  `useOrgs.ts`/`useMe.ts`:类型随新契约(去 group_id、加 enterprises+display_name);`Account.tsx`:企业行显示 `display_name`,无访问组维度;enterprise-admin 显示「邀请成员」入口 → 调 `POST /auth/orgs/invite`。
- [x] **Step 3: 跑绿门禁** `make fe-types && cd frontend && npx vitest run && npm run lint && npm run build` → 全绿。
- [x] **Step 4: Commit** `git commit -m "feat(frontend): 账户页企业 display_name + enterprise-admin 邀请入口;去 group_id"`

---

## Task 10: 全绿门禁 + owner-readable runbook + 合并准备

**Files:** Modify 本计划(嵌 runbook);全门禁。

- [x] **Step 1: 全绿门禁** `make gen && make lint && uv run pytest -q` + `cd frontend && npx vitest run && npm run build`;`make gen` 后 `git diff --exit-code libs/contracts_gen/` clean。
- [x] **Step 2: runbook 写入本文件 + Commit**(见下)。
- [x] **Step 3: 独立 code review**(superpowers:requesting-code-review)整分支,重点:企业硬隔离不被绕过(org claim 伪造防线)、多-org `organization:*` 固化、group_id 无残留、宪法 ≡ 实现、契约/生成物/前端类型一致。修 Critical/Important。

---

## 手动验收 Runbook(owner 逐步跑,白话)

> 仓库根、终端逐条。前置:Docker 在跑。

- [ ] **1. 起栈(含 KC organizations + mailpit)+ 置备 org**
  - `make deps-dev`(等 KC 起)→ `uv run python scripts/provision_orgs.py`
  - 应看到:org `ent-demo` 建好、alice 以 unmanaged 加入、旧 g- 子组已移除。
- [ ] **2. 登录看企业(US1/US2)**
  - `make up` → `localhost:8090` 登录 alice → 「我的账户」显示企业 **"Demo 企业"**(显示名,非 alias/UUID)、角色;跨企业不可见他企业数据。
- [ ] **3. 注册按域自动归属(US3)**
  - 登出 → 注册页用 `someone@acme.test` 注册 → 登录后**已是 Demo 企业成员**,直接能上传/见数据(**不撞无企业 403**)。
  - 再用 `x@nodomain.test` 注册 → **显式提示待分配/拒绝**,不悬空。
- [ ] **4. 邀请(US4)**
  - 用 enterprise-admin 账户 → 账户页「邀请成员」填 `newhire@x.com` → `localhost:8025`(mailpit)收到邀请邮件 → 接受 → 成 Demo 企业成员。
- [ ] **5. 全链路不回归(US2-AC3)**
  - 上传 coco → 注册到目录 → 建作业 → 管线跑通 → 数据目录可见(全程在 **`ent-demo`** 不透明 alias 下,企业隔离 + owner 不变)。
- [ ] **6. 隔离负例**
  - 跨企业访问被拒;平台管理员(无企业)直达 /admin/*、不被"待分配"误伤。

> 任一步对不上贴输出。全过 = 企业=org 全链路通(建企业→注册按域归属/邀请→登录→数据全链路),企业硬隔离 + owner 不回归。

---

## Self-Review
- **Spec 覆盖**:US1 企业一级实体→Task1/2;US2 隔离不破→Task2/3/4 + runbook5/6;US3 注册按域→Task1/7 + runbook3;US4 邀请→Task7 + runbook4;US5 两级无访问组→Task2/4(去 group);US6 迁移→Task1 provision 脚本(幂等)+ Task6 重 bootstrap。FR-001~008 + FR-002b(display_name)→ Task2/3/5/9。✅
- **探针已钉死项**:claim=alias 数组(Task2 按 list 解析)、默认进 access token(无勾选任务)、多-org `organization:*`(Task3 Step3)、enterprise_id=alias(Task5/6)、成员 unmanaged(Task1)。✅
- **Placeholder 扫描**:各 task 给确切文件 + 关键代码 + 测试断言 + 命令;注册自动归属/邀请完整流标 e2e(机制已实测,非 TBD)。✅
- **类型一致**:`parse_context(sub, organization, realm_roles)`、`Membership(enterprise_id, role)`、`role_in(enterprise_id)`、`Resource`/`AuditEvent` 去 group_id —— 跨 Task2/3/4 一致。✅
- **承重墙**:enterprise_id 改值跨契约/Gravitino/OSS/审计(Task4/5/6 具名);宪法同批落(Task8);多-org claim 坑缓解固化(Task3)。✅
- **宪法 ≡ 实现**:Task8 与代码同批,不提前描述未建态。✅
