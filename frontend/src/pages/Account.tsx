import { useOrgs } from '../auth/useOrgs'
import { useMe } from '../auth/useMe'

// 我的账户(US6 / FR-004):显示当前用户真实信息(用户名/邮箱)+ 真实「组内角色」。
// 用户名/邮箱来自 GET /auth/me(Keycloak token claims:preferred_username/email);
// 角色来自 GET /v1/me/orgs 的 memberships[].role(member|group-admin|enterprise-admin),
// 不可用 is_platform_admin(全局平台管理员标志)派生角色。
// 企业/组「显示名」是后端缺口(只有 e-/g- 内部 ID),FR-004 禁渲染原始 ID,故诚实占位。

const ROLE_LABEL: Record<string, string> = {
  member: '成员',
  'group-admin': '组管理员',
  'enterprise-admin': '企业管理员',
}

export function Account() {
  const { orgs, loading } = useOrgs()
  const { me } = useMe()

  if (loading) return <div className="text-slate-400 text-sm">加载中…</div>
  if (!orgs) return <div className="text-slate-400 text-sm">无法获取账户信息。</div>

  const displayName = me?.username || orgs.user      // 真实用户名,回退 sub
  const email = me?.email || null
  const initial = displayName.slice(0, 1).toUpperCase()
  const rawRole = orgs.memberships[0]?.role
  const role = rawRole ? (ROLE_LABEL[rawRole] ?? rawRole) : '—'

  return (
    <div className="max-w-3xl">
      <div className="bg-white border border-slate-200/70 rounded-2xl p-7 shadow-sm">
        <div className="flex items-center gap-4 mb-6">
          <span className="h-16 w-16 rounded-full bg-[#E0E4FF] text-[#6366F1] grid place-items-center text-2xl font-semibold">{initial}</span>
          <div>
            <div className="font-semibold text-xl">{displayName}</div>
            <div className="text-sm text-slate-500">{email ?? '经 BFF 会话 · 前端不持 token'}</div>
          </div>
        </div>
        <dl className="grid sm:grid-cols-2 gap-y-5 gap-x-6 text-sm">
          <div>
            <dt className="text-xs text-slate-500 mb-1">用户名</dt>
            <dd className="font-medium">{displayName}</dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500 mb-1">邮箱</dt>
            <dd className="font-medium">{email ?? '—'}</dd>
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
        </dl>
      </div>
    </div>
  )
}
