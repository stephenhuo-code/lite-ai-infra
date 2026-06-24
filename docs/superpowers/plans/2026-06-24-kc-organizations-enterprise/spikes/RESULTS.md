# KC 探针实测 RESULTS — Organizations token claim / 多-org / 注册 / 邀请

> 状态:**实测事实(钉死 DoR④)**。日期 2026-06-24。KC **26.6.2**(`--features=organization`,实测)。
> 方法:在 **throwaway realm `kcprobe`** 里建 org + client + 用户,经 admin REST + direct-grant 抓**真实 access token**,跑完即删该 realm(**未触碰 lite-ai realm**)。
> 这套实测**修正了 [上游 spike](../../../spikes/2026-06-23-kc-organizations-vs-groups.md) 的若干预期**(下方标 ⚠️)。

## 关键结论(直接喂 design / plan)

### F1 — `organization` claim = **org alias 的数组**(不是对象,不含 org id)⚠️
默认 `oidc-organization-membership-mapper`(`multivalued=true`)下,access token:
```json
"organization": ["acme"]
```
- `multivalued=false` → `"organization": "acme"`(单字符串)。
- **claim 里只有 alias,没有 org id(UUID)、没有 attributes**。⚠️ spike 预期"alias-keyed 对象 + 勾选带 id"**不成立**(至少默认 mapper 如此)。
- **设计推论**:**`enterprise_id` = org `alias`**(token 唯一可靠携带的企业标识)。owner 要"不透明 id" → **把 alias 设为不透明值**(如 `ent-<随机>`,非人工 `e-XXXX`),即满足"不透明"又被 token 携带。**不依赖 KC org UUID**(它不进 token)。

### F2 — claim **默认就进 access token** ✅(spike 担心多余)⚠️
mapper 默认 `access.token.claim=true`(实测 config)。⚠️ spike "默认不进 access token,需手动勾"在 26.6.2 **不成立**——无需额外勾选。

### F3 — `organization` scope **非默认**,需显式请求(且多-org 必须用选择器)
- realm 默认 client scopes 不含 OIDC `organization`(只有 `saml_organization`)→ client 需把 `organization` 列为 default/optional 或请求方带 `scope=organization`。
- **多-org 坑实测复现**(#39402/#43635):用户属 2 个 org 时,`scope=openid organization`(无选择器)→ **`organization` claim = `null`(消失)**。
- **缓解实测有效**:
  - `scope=openid organization:*` → `["acme","beta"]`(全部)✅
  - `scope=openid organization:acme` → `["acme"]`(指定)✅
- **设计推论**:**BFF/网关发起认证必须带动态 scope `organization:*`** 并在 client scope 固化,否则多-org 用户拿不到企业归属。

### F4 — 成员类型:已有 realm 用户加入 org = **UNMANAGED** ✅
先建 realm 用户、再 `POST organizations/{id}/members` → `membershipType=UNMANAGED`(印证迁移要点:存量用户以 unmanaged 加入保账号)。

### F5 — org id 形态:**标准 UUID**
`bfd6c424-19db-4913-8b89-6e85b3a4bc9d`。若将来确需以 id 作标识:`replace("-","_")` 后为合法 Gravitino metalake 名(`[a-z0-9_]`)。但**本设计用 alias 不用 id**(见 F1),metalake = `alias.replace("-","_")`。

### F6 — 邀请 API 端点存在 ✅(完整流需 SMTP)
`POST /admin/realms/{realm}/organizations/{id}/members/invite-user`(form: email/firstName/lastName)端点可调;dev 无 SMTP → 返 500(发邮件失败),**端点与契约证实可用**;另有 `invite-existing-user`。完整邀请接受流 → **plan 里配 dev SMTP(如 mailpit)或 browser e2e 验**。

### F7 — 注册自动归属:机制就位,完整流待 e2e
realm `registrationAllowed=true` + `organizationsEnabled=true` + org `domains=[acme.test]` 就位;按域自动归属依赖 KC self-registration + identity-first 浏览器流,**admin REST 无法单测** → **plan 里 browser e2e 验**(注册 `x@acme.test` → 自动成 acme 成员);**无匹配域**行为一并 e2e 钉死。

## 对 design 的修订(已据此回改 design.md)
- enterprise_id 来源:**org alias(设为不透明值)**,非 KC org UUID(F1);metalake = `alias.replace("-","_")`。
- token:`organization` claim 默认进 access token(F2,删"需勾选"任务)。
- **承重墙缓解钉死**:BFF 认证请求带 `scope=organization:*`(F3),parse_context 读 alias 数组;v1 单 org → 取唯一;多 org → 沿用 `enterprise_of` 0/多显式拒。
- parse_context 入参:读 `organization`(list[str] of alias);角色另由 org 属性/realm role(F1 显示 claim 不含角色 → 角色用 realm role 或 org attribute,plan Task 探针二次确认其 claim 形态)。

## 复现命令(节选,realm 已删)
```
# admin token(master/admin-cli/admin/admin)→ 建 realm kcprobe(organizationsEnabled)
# 建 client probe(directAccessGrants+secret)、org acme(domain acme.test)、user alice@acme.test
# POST organizations/{id}/members 加成员 → membershipType=UNMANAGED
# token: grant_type=password client_id=probe scope="openid organization:*" → 解 access_token.organization
# 多 org:再建 beta 加成员 → 无选择器 claim=null;organization:* → ["acme","beta"]
# DELETE realms/kcprobe(清理)
```
