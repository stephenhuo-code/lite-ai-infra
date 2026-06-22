import { useMe } from '../auth/useMe'

// 我的账户(US6 / FR-004):显示当前用户 + 会话/权限信息。
// 真实 /auth/me 仅返回 {user, is_platform_admin, csrf}——刻意不暴露 enterprise_name/
// memberships 与任何 e-/g- 内部 ID(组织模型硬约束)。

export function Account() {
  const { me, loading } = useMe()

  if (loading) return <div className="text-slate-400 text-sm">加载中…</div>
  if (!me) return <div className="text-slate-400 text-sm">无法获取账户信息。</div>

  const initial = me.user.slice(0, 1).toUpperCase()
  const role = me.is_platform_admin ? '平台管理员' : '成员'

  return (
    <div className="grid lg:grid-cols-3 gap-5">
      <div className="bg-white border border-slate-200/70 rounded-2xl p-7 lg:col-span-2 shadow-sm">
        <div className="flex items-center gap-4 mb-6">
          <span className="h-16 w-16 rounded-full bg-[#E0E4FF] text-[#6366F1] grid place-items-center text-2xl font-semibold">{initial}</span>
          <div>
            <div className="font-semibold text-xl">{me.user}</div>
            <div className="text-sm text-slate-500">经 BFF 会话 · 前端不持 token</div>
          </div>
        </div>
        <dl className="grid sm:grid-cols-2 gap-y-5 gap-x-6 text-sm">
          <div>
            <dt className="text-xs text-slate-500 mb-1">用户</dt>
            <dd className="font-medium">{me.user}</dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500 mb-1">角色</dt>
            <dd>
              <span className="inline-flex items-center rounded-lg bg-[#EEF0FF] text-[#4F46E5] text-xs font-medium px-2.5 py-1">{role}</span>
            </dd>
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
