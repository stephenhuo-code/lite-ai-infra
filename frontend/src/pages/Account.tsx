import { useState } from 'react'
import { useOrgs } from '../auth/useOrgs'
import { useMe } from '../auth/useMe'
import { api } from '../api/client'

// 我的账户(US6 / FR-004 / FR-002b):显示当前用户真实信息(用户名/邮箱)+ 真实角色 + 企业**显示名**。
// 用户名/邮箱来自 GET /auth/me(Keycloak token claims:preferred_username/email);
// 角色 + 企业显示名来自 GET /v1/me/orgs(memberships[].role、enterprises[].display_name)。
// 身份降两级(ADR-025):无访问组层;§1.4 禁渲染不透明 alias → 界面用 display_name(空则回退 alias)。
// enterprise-admin 见「邀请成员」入口 → POST /auth/orgs/invite。

const ROLE_LABEL: Record<string, string> = {
  member: '成员',
  'enterprise-admin': '企业管理员',
}

export function Account() {
  const { orgs, loading } = useOrgs()
  const { me } = useMe()
  const [email, setEmail] = useState('')
  const [inviteMsg, setInviteMsg] = useState<string | null>(null)
  const [inviting, setInviting] = useState(false)

  if (loading) return <div className="text-slate-400 text-sm">加载中…</div>
  if (!orgs) return <div className="text-slate-400 text-sm">无法获取账户信息。</div>

  const displayName = me?.username || orgs.user      // 真实用户名,回退 sub
  const userEmail = me?.email || null
  const initial = displayName.slice(0, 1).toUpperCase()
  const rawRole = orgs.memberships[0]?.role
  const role = rawRole ? (ROLE_LABEL[rawRole] ?? rawRole) : '—'
  const ent = orgs.enterprises?.[0]
  // §1.4:界面用企业显示名;无显示名则诚实回退 alias(不悬空、不渲染 UUID)。
  const entLabel = ent ? (ent.display_name || ent.alias) : '—'
  const isEntAdmin = rawRole === 'enterprise-admin'

  async function invite() {
    const e = email.trim()
    if (!e) return
    setInviting(true)
    setInviteMsg(null)
    try {
      await api.post('/auth/orgs/invite', { email: e })
      setInviteMsg(`已向 ${e} 发出邀请`)
      setEmail('')
    } catch {
      setInviteMsg('邀请失败,请重试')
    } finally {
      setInviting(false)
    }
  }

  return (
    <div className="max-w-3xl">
      <div className="bg-white border border-slate-200/70 rounded-2xl p-7 shadow-sm">
        <div className="flex items-center gap-4 mb-6">
          <span className="h-16 w-16 rounded-full bg-[#E0E4FF] text-[#6366F1] grid place-items-center text-2xl font-semibold">{initial}</span>
          <div>
            <div className="font-semibold text-xl">{displayName}</div>
            <div className="text-sm text-slate-500">{userEmail ?? '经 BFF 会话 · 前端不持 token'}</div>
          </div>
        </div>
        <dl className="grid sm:grid-cols-2 gap-y-5 gap-x-6 text-sm">
          <div>
            <dt className="text-xs text-slate-500 mb-1">用户名</dt>
            <dd className="font-medium">{displayName}</dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500 mb-1">邮箱</dt>
            <dd className="font-medium">{userEmail ?? '—'}</dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500 mb-1">角色</dt>
            <dd>
              <span className="inline-flex items-center rounded-lg bg-[#EEF0FF] text-[#4F46E5] text-xs font-medium px-2.5 py-1">{role}</span>
            </dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500 mb-1">企业</dt>
            {/* §1.4:渲染企业显示名,绝不渲染不透明 alias/UUID。 */}
            <dd className="font-medium">{entLabel}</dd>
          </div>
        </dl>

        {isEntAdmin && (
          <div className="mt-7 pt-6 border-t border-slate-200/70">
            <div className="text-sm font-medium mb-2">邀请成员</div>
            <div className="text-xs text-slate-500 mb-3">向 TA 的邮箱发送加入本企业的邀请。</div>
            <div className="flex gap-2">
              <input
                type="email"
                value={email}
                onChange={e => setEmail(e.target.value)}
                placeholder="受邀人邮箱"
                className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
              <button
                onClick={invite}
                disabled={inviting || !email.trim()}
                className="rounded-lg bg-[#4F46E5] text-white text-sm font-medium px-4 py-2 disabled:opacity-50"
              >发送邀请</button>
            </div>
            {inviteMsg && <div className="text-xs text-slate-500 mt-2">{inviteMsg}</div>}
          </div>
        )}
      </div>
    </div>
  )
}
