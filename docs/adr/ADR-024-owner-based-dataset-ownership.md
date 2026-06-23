# ADR-024: 数据集归属 = owner_user(上传用户) — can() v1 改 owner-only,group 访问推迟 Cerbos v2

- 状态：Accepted（2026-06-24，owner 拍板）
- 决策人：owner
- 相关：**修订 ADR-010**（资源归属 group→owner_user、group 降为访问维度）、**修订 ADR-011**（v1 can() = 企业硬隔离 + owner-only;group 访问 → Cerbos v2）、**修订 ADR-016**（fileset 归属/路径由 owner_group 改 owner_user）；constitution §1.5(归属编码在资源)/ §1.6(硬隔离);design spec

---

## Context

ADR-010/016 把"资源归属单元"定为 **用户组(group)**：私有资源 `group_id` 匹配或同组可见，OSS 路径 `e-XXXX/g-YYYY/...`。落地 catalog-driven-datasets 时 owner 重新厘清归属语义：

1. **数据集的真实主人是上传它的那个用户(`ctx.user`=token `sub`)，不是组。** 把归属挂在 group 上，会让"谁能删/改这份数据"模糊（同组任意成员都能动），与"group 是协作/访问维度、不是所有权维度"相矛盾。
2. **企业仍是硬隔离边界**（不变，§1.6）。
3. **跨用户分享 / group scope 访问** 是真实需求，但属细粒度授权，留给 Cerbos（v2 / v-next）做 group 之上的叠加层（与 ADR-011 升级路径一致），v1 不交付。

因此 v1 把归属真相源从 group 收敛到 **owner_user**，can() 不再按 group 隔离数据集。

## Decision

### 1. 归属真相源 = `owner_user`

- 数据集（及同模型下的 job 等资源）的归属真相源 = **`owner_user` = 上传/创建用户的 token `sub`**。
- **OSS 路径 / 隔离 / 可见性按 owner**：物理路径由 `e-XXXX/g-YYYY/...` 改为 **`e-XXXX/{user}/...`**（企业前缀不变,硬隔离不变;group 段去除）。
- `group_id` 保留为**可选属性**，供 audit / 未来 Cerbos v2 的 group 访问维度用，**不参与 v1 授权决策**。

### 2. v1 `can()` = 企业硬隔离 + owner-only

```
1. platform-admin 走业务路径 → deny(必须 /admin/*,沿用)
2. 企业硬隔离(§1.6):ctx 无任一 membership 命中 resource.enterprise_id → deny(cross-enterprise)
3. GPU 配额门槛:job.submit 且 gpu>4 且非 enterprise-admin → deny(门槛由 group-admin 改 enterprise-admin)
4. owner-only:owner==ctx.user 或 enterprise-admin(或 platform-admin 走特权)→ allow;否则 deny
   (owner=None=资源无主/S0 stub 解析不出 owner → 放行本企业成员)
```

- **group 访问（scope / 跨用户共享）= Cerbos v2**：v1 的 can() 不再读 `group_id` 判隔离，不再有"同组 allow / 跨组 deny"。
- **GPU>4 配额门槛由 group-admin 改 enterprise-admin**（owner 模型下无 group-admin 这层授权角色）。

### 3. 否决项

- **保留 group 归属**（ADR-010/016 原案）：否决。与"group = 访问/权限维度，不是所有权维度"矛盾；同组任意成员可删改他人数据，归属不清。

## Consequences

### 正面
- 归属清晰：谁上传谁拥有，删改权专属 owner（+ enterprise-admin / platform-admin 特权）。
- can() 更薄：去掉 group_id 判隔离分支，只剩企业硬隔离 + owner-only，单一出入口 + 测试覆盖。
- 企业硬隔离（灾难级边界）完全不变。

### 负面 / 代价（接受）
- v1 无 group 内共享/可见：同组他人的数据集默认不可见（need-to-share 留 v2 Cerbos 叠加层）。
- 路径含 `{user}`：用户级前缀，OSS 列举/STS 凭据按 user 前缀（非 group 前缀）。

### 升级路径
- v2 Cerbos：per-user / per-resource grant + group scope 作 owner 之上的**叠加授权层**（ADR-011 升级路径），`group_id` 属性此时启用；can() 签名不变，handler 零改。

---

## 修订指针（被本 ADR 修订的条目）

- **ADR-010**：§2「资源归属：企业共享 + 用户组私有」→ 归属真相源改为 `owner_user`；group 降为访问维度（非所有权单元）。附录 A 第 5 条「私有资源还须 group_id 匹配」→ 私有资源按 owner_user 判，group 不参与 v1 决策。
- **ADR-011**：v1 `can()` 的"同组成员"derived role → v1 收敛为 owner-only（企业硬隔离 + owner==user / enterprise-admin）;group 访问（same_group_member / shared_reader）整体下放 Cerbos v2。
- **ADR-016**：fileset 归属真相源由 `owner_group` 改 `owner_user`;OSS 物理路径 `e-XXXX/g-YYYY/...` → `e-XXXX/{user}/...`;`owner_group`/`group_id` 保留为属性供 audit/v2。
