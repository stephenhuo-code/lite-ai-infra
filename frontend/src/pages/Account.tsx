import { useOrgs } from '../auth/useOrgs'

// 我的账户(US6 / FR-004):显示当前用户 + 真实「组内角色」。
// 角色来自 GET /v1/me/orgs 的 memberships[].role(member|group-admin|enterprise-admin),
// 不可用 is_platform_admin(全局平台管理员标志)派生角色——一个 group-admin 的
// is_platform_admin=False,若据此派生会被错显成「成员」。
// 企业/组「显示名」是后端缺口:后端只有 e-/g- 内部 ID,无显示名字段;
// FR-004 禁止界面暴露 e-/g- ID,故此处诚实占位「显示名待后端补充(vN+)」,
// 不渲染原始 ID。

const ROLE_LABEL: Record<string, string> = {
  member: '成员',
  'group-admin': '组管理员',
  'enterprise-admin': '企业管理员',
}

export function Account() {
  const { orgs, loading } = useOrgs()

  if (loading) return <div className="text-slate-400 text-sm">加载中…</div>
  if (!orgs) return <div className="text-slate-400 text-sm">无法获取账户信息。</div>

  const initial = orgs.user.slice(0, 1).toUpperCase()
  const rawRole = orgs.memberships[0]?.role
  const role = rawRole ? (ROLE_LABEL[rawRole] ?? rawRole) : '—'

  return (
    <div className="grid lg:grid-cols-3 gap-5">
      <div className="bg-white border border-slate-200/70 rounded-2xl p-7 lg:col-span-2 shadow-sm">
        <div className="flex items-center gap-4 mb-6">
          <span className="h-16 w-16 rounded-full bg-[#E0E4FF] text-[#6366F1] grid place-items-center text-2xl font-semibold">{initial}</span>
          <div>
            <div className="font-semibold text-xl">{orgs.user}</div>
            <div className="text-sm text-slate-500">经 BFF 会话 · 前端不持 token</div>
          </div>
        </div>
        <dl className="grid sm:grid-cols-2 gap-y-5 gap-x-6 text-sm">
          <div>
            <dt className="text-xs text-slate-500 mb-1">用户</dt>
            <dd className="font-medium">{orgs.user}</dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500 mb-1">角色</dt>
            <dd>
              <span className="inline-flex items-center rounded-lg bg-[#EEF0FF] text-[#4F46E5] text-xs font-medium px-2.5 py-1">{role}</span>
            </dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500 mb-1">企业 / 用户组</dt>
            {/* 后端无企业/组显示名字段;FR-004 禁渲染 e-/g- 内部 ID,故诚实占位。 */}
            <dd className="text-slate-500">显示名待后端补充(vN+)</dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500 mb-1">会话</dt>
            <dd className="text-slate-600">经 BFF · 前端不持 token</dd>
          </div>
        </dl>
      </div>
      <aside className="bg-white border border-slate-200/70 rounded-2xl p-6 text-sm shadow-sm">
        <h3 className="font-semibold mb-2">用户组 = 权限维度</h3>
        <p className="text-slate-600 text-[13px] leading-relaxed">
          企业、用户组是<b>身份与组织</b>概念(平台→企业→用户组→用户)。数据集<b>归属上传者</b>,不“属于”某个组;用户组是给数据集<b>授予访问权限</b>的维度。你看到的,是你有权访问的数据。
        </p>
      </aside>
    </div>
  )
}
