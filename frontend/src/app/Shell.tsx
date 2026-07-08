import { useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { useOrgs } from '../auth/useOrgs'

// 两栏应用外壳:最左窄「图标栏」(大图标+小字的一级菜单)+ 可折叠「二级面板」(列当前一级项的子页)。
// 一级 = 任务 / 智能体 / 数据 / 工作台 + 底部「我的账户」;任务/账户无子页(全宽渲染)。
// 视觉沿用全站靛蓝 #6366F1;登出/无企业引导行为不变。

type SubItem = { to: string; label: string; adminOnly?: boolean }
type Section = { key: string; label: string; icon: React.ReactNode; to?: string; children?: SubItem[] }

const SECTIONS: Section[] = [
  { key: 'tasks', label: '任务', to: '/workspace', icon: (
    <svg className="w-6 h-6" fill="none" stroke="currentColor" strokeWidth="1.7" viewBox="0 0 24 24"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>
  ) },
  { key: 'agents', label: '智能体', icon: (
    <svg className="w-6 h-6" fill="none" stroke="currentColor" strokeWidth="1.7" viewBox="0 0 24 24"><rect x="4" y="7" width="16" height="12" rx="2"/><path d="M9 7V5a3 3 0 016 0v2M9 13h.01M15 13h.01"/></svg>
  ), children: [
    { to: '/agents', label: '智能体库' },
    { to: '/model-config', label: '模型配置', adminOnly: true },
  ] },
  { key: 'data', label: '数据', icon: (
    <svg className="w-6 h-6" fill="none" stroke="currentColor" strokeWidth="1.7" viewBox="0 0 24 24"><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/></svg>
  ), children: [
    { to: '/catalog', label: '数据目录' },
    { to: '/datasets', label: '数据集' },
  ] },
  { key: 'work', label: '工作台', icon: (
    <svg className="w-6 h-6" fill="none" stroke="currentColor" strokeWidth="1.7" viewBox="0 0 24 24"><circle cx="6" cy="6" r="2.5"/><circle cx="6" cy="18" r="2.5"/><circle cx="18" cy="12" r="2.5"/><path d="M8.5 6H14a2 2 0 012 2v1.5M8.5 18H14a2 2 0 002-2v-1.5"/></svg>
  ), children: [
    { to: '/create', label: '创建作业' },
    { to: '/pipelines', label: '数据管线' },
  ] },
]

const ACCOUNT: Section = { key: 'account', label: '我的账户', to: '/account', icon: (
  <svg className="w-6 h-6" fill="none" stroke="currentColor" strokeWidth="1.7" viewBox="0 0 24 24"><circle cx="12" cy="8" r="3.5"/><path d="M5 20c0-3.3 3.1-6 7-6s7 2.7 7 6"/></svg>
) }

async function logout() {
  // RP-initiated logout:POST 清本地会话(CSRF 保护)→ 整页跳 BFF 返回的 KC end_session(结束 SSO,无缝回登录页)
  try {
    const r = await api.post('/auth/logout')
    if (r?.end_session) { window.location.assign(r.end_session); return }
  } catch { /* 降级:拿不到 end_session 仍回登录 */ }
  window.location.assign('/auth/login')
}

// 无企业(待分配)友好态:注册了但未被任何企业授予成员(C 方案,加入企业由管理员授予)。
// 数据页改显此引导,而非数据请求 403 的红色"加载失败"(FR-003 显式可理解提示)。
function NoEnterpriseNotice() {
  return (
    <div className="grid place-items-center" style={{ minHeight: '60vh' }}>
      <div className="text-center max-w-md px-6">
        <div className="mx-auto mb-4 h-14 w-14 rounded-2xl bg-[#EEF0FF] grid place-items-center" style={{ color: '#6366F1' }}>
          <svg className="w-7 h-7" fill="none" stroke="currentColor" strokeWidth="1.7" viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M3 9h18" /><path d="M9 14h6" /></svg>
        </div>
        <h2 className="text-lg font-semibold text-slate-800">你还未加入任何企业</h2>
        <p className="text-sm text-slate-500 mt-2 leading-relaxed">
          你的账号已创建,但尚未归属企业。请联系<b>企业管理员</b>将你加入企业后,再使用数据集 / 数据目录 / 作业等功能。
        </p>
        <NavLink to="/account" className="inline-block mt-5 text-sm font-medium px-4 py-2 rounded-xl text-white" style={{ background: '#6366F1' }}>
          去「我的账户」查看
        </NavLink>
      </div>
    </div>
  )
}

// 图标栏一级项:大图标 + 小字,竖排,不缩进。
function RailItem({ section, active, onClick }: { section: Section; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      title={section.label}
      aria-label={section.label}
      className={
        'flex flex-col items-center gap-1 w-full py-2.5 rounded-xl text-[11px] font-medium transition-colors ' +
        (active ? 'bg-[#EEF0FF] text-[#4F46E5]' : 'text-slate-500 hover:bg-slate-50 hover:text-slate-700')
      }
    >
      {section.icon}
      <span>{section.label}</span>
    </button>
  )
}

export function Shell() {
  const [collapsed, setCollapsed] = useState(false)
  const { orgs, loading } = useOrgs()
  const location = useLocation()
  const navigate = useNavigate()
  // 已加载且无企业成员且非平台管理员 → 待分配态(数据页拦截,/account 放行)。
  const noEnterprise = !loading && !!orgs && (orgs.memberships?.length ?? 0) === 0 && !orgs.is_platform_admin
  // 企业管理员:任一 membership.role === 'enterprise-admin'。adminOnly 子页(模型配置)仅其可见(仅 UX 门,服务端独立强制)。
  const isEnterpriseAdmin = !!orgs?.memberships?.some(m => m.role === 'enterprise-admin')

  const visibleChildren = (s: Section): SubItem[] =>
    (s.children ?? []).filter(c => !c.adminOnly || isEnterpriseAdmin)

  // 当前路由归属哪个一级项(图标栏高亮 + 决定二级面板)。
  const pathname = location.pathname
  const matchSection = (s: Section) => s.to === pathname || (s.children ?? []).some(c => c.to === pathname)
  const activeSection: Section =
    [...SECTIONS, ACCOUNT].find(matchSection) ?? SECTIONS[0]

  const railTarget = (s: Section) => s.to ?? visibleChildren(s)[0]?.to ?? '/'
  const secondaryItems = visibleChildren(activeSection)
  const showSecondary = secondaryItems.length > 0 && !collapsed

  return (
    <div className="flex min-h-screen bg-slate-50 text-slate-800">
      {/* 图标栏(一级菜单):大图标+小字,竖排,不缩进 */}
      <aside className="w-20 shrink-0 h-screen sticky top-0 bg-white border-r border-slate-200/70 flex flex-col">
        <div className="h-16 flex items-center justify-center border-b border-slate-100">
          <div className="h-9 w-9 rounded-xl grid place-items-center text-white shrink-0 shadow-sm" style={{ background: 'linear-gradient(to bottom right, #6366F1, #d946ef)' }} title="Lite-AI">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="1.7" viewBox="0 0 24 24"><path d="M12 3l1.9 4.8L18.8 9.7l-4.9 1.5L12 16l-1.9-4.8L5.2 9.7l4.9-1.9z"/></svg>
          </div>
        </div>
        <nav className="flex-1 p-2 space-y-1">
          {SECTIONS.map(s => (
            <RailItem key={s.key} section={s} active={activeSection.key === s.key} onClick={() => navigate(railTarget(s))} />
          ))}
        </nav>
        <div className="p-2 border-t border-slate-100">
          <RailItem section={ACCOUNT} active={activeSection.key === ACCOUNT.key} onClick={() => navigate(railTarget(ACCOUNT))} />
        </div>
      </aside>

      {/* 二级面板:仅含子页的一级项显示;列该节子页 */}
      {showSecondary && (
        <aside data-testid="secondary-nav" className="w-52 shrink-0 h-screen sticky top-0 bg-white border-r border-slate-200/70 flex flex-col">
          <div className="h-16 flex items-center gap-2 px-4 border-b border-slate-100">
            <span className="font-semibold text-[15px] text-slate-800">{activeSection.label}</span>
            <button
              onClick={() => setCollapsed(true)}
              aria-label="折叠面板"
              title="折叠"
              className="ml-auto p-1.5 rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-600 shrink-0"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="1.8" viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/><path d="M14 9l-2 3 2 3"/></svg>
            </button>
          </div>
          <nav className="p-3 space-y-1 flex-1">
            {secondaryItems.map(item => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  'flex items-center px-3 py-2.5 rounded-xl text-[15px] transition-colors ' +
                  (isActive ? 'bg-[#EEF0FF] text-[#4F46E5] font-semibold' : 'text-slate-600 hover:bg-slate-50')
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          <div className="p-3 border-t border-slate-100 h-12 flex items-center">
            <span className="text-[11px] text-slate-400">v0.1 · 数据域</span>
          </div>
        </aside>
      )}

      <main className="flex-1 min-w-0">
        <header className="h-16 sticky top-0 z-20 bg-white/85 backdrop-blur border-b border-slate-200/70 flex items-center gap-3 px-7">
          {/* 面板折叠时:在顶栏左侧给一个展开入口(仅当前一级项有子页时) */}
          {secondaryItems.length > 0 && collapsed && (
            <button
              onClick={() => setCollapsed(false)}
              aria-label="展开面板"
              title="展开"
              className="p-1.5 rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-600"
            >
              <svg className="w-5 h-5 scale-x-[-1]" fill="none" stroke="currentColor" strokeWidth="1.8" viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/><path d="M14 9l-2 3 2 3"/></svg>
            </button>
          )}
          <div className="ml-auto flex items-center gap-3">
            <button
              onClick={logout}
              className="inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-red-600 hover:bg-red-50 rounded-lg px-3 py-1.5 transition-colors"
            >
              <svg className="w-[18px] h-[18px]" fill="none" stroke="currentColor" strokeWidth="1.8" viewBox="0 0 24 24"><path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4" /><path d="M16 17l5-5-5-5" /><path d="M21 12H9" /></svg>
              登出
            </button>
          </div>
        </header>

        <div className="p-7">
          {noEnterprise && location.pathname !== '/account'
            ? <NoEnterpriseNotice />
            : <Outlet />}
        </div>
      </main>
    </div>
  )
}
