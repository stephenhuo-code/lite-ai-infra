import { useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { api } from '../api/client'

// 可折叠应用外壳(US1 鉴权壳):侧栏 w-64↔w-16、顶栏(登出)、<Outlet/>。
// 视觉照高保真原型 docs/superpowers/prototypes/2026-06-22-data-domain-hifi.html(靛蓝 #6366F1)。
// 顶栏不显示企业名:后端无 enterprise_name 字段(vN+ 缺口),不假装显示企业名,
// 也不保留死 prop。折叠/登出/导航行为保持不动。

type NavItem = { to: string; label: string; group?: string; icon: React.ReactNode }

const NAV: NavItem[] = [
  { to: '/datasets', label: '数据集', group: '数据', icon: (
    <svg className="w-[22px] h-[22px]" fill="none" stroke="currentColor" strokeWidth="1.7" viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></svg>
  ) },
  { to: '/catalog', label: '数据目录', icon: (
    <svg className="w-[22px] h-[22px]" fill="none" stroke="currentColor" strokeWidth="1.7" viewBox="0 0 24 24"><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/></svg>
  ) },
  { to: '/pipelines', label: '数据管线', group: '作业', icon: (
    <svg className="w-[22px] h-[22px]" fill="none" stroke="currentColor" strokeWidth="1.7" viewBox="0 0 24 24"><circle cx="6" cy="6" r="2.5"/><circle cx="6" cy="18" r="2.5"/><circle cx="18" cy="12" r="2.5"/><path d="M8.5 6H14a2 2 0 012 2v1.5M8.5 18H14a2 2 0 002-2v-1.5"/></svg>
  ) },
  { to: '/create', label: '创建作业', icon: (
    <svg className="w-[22px] h-[22px]" fill="none" stroke="currentColor" strokeWidth="1.7" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 8v8M8 12h8"/></svg>
  ) },
  { to: '/account', label: '我的账户', group: '账户', icon: (
    <svg className="w-[22px] h-[22px]" fill="none" stroke="currentColor" strokeWidth="1.7" viewBox="0 0 24 24"><circle cx="12" cy="8" r="3.5"/><path d="M5 20c0-3.3 3.1-6 7-6s7 2.7 7 6"/></svg>
  ) },
]

const navItemBase = 'nav-item flex items-center gap-3 px-3 py-2.5 rounded-xl text-[15px] transition-colors'

async function logout() {
  // RP-initiated logout:POST 清本地会话(CSRF 保护)→ 整页跳 BFF 返回的 KC end_session(结束 SSO,无缝回登录页)
  try {
    const r = await api.post('/auth/logout')
    if (r?.end_session) { window.location.assign(r.end_session); return }
  } catch { /* 降级:拿不到 end_session 仍回登录 */ }
  window.location.assign('/auth/login')
}

export function Shell() {
  const [collapsed, setCollapsed] = useState(false)
  const asideWidth = collapsed ? 'w-16' : 'w-64'

  return (
    <div className="flex min-h-screen bg-slate-50 text-slate-800">
      <aside className={`${asideWidth} shrink-0 h-screen sticky top-0 bg-white border-r border-slate-200/70 flex flex-col transition-[width] duration-150`}>
        <div className="h-16 flex items-center gap-2.5 px-4 border-b border-slate-100">
          <div className="h-9 w-9 rounded-xl grid place-items-center text-white shrink-0 shadow-sm" style={{ background: 'linear-gradient(to bottom right, #6366F1, #d946ef)' }}>
            <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="1.7" viewBox="0 0 24 24"><path d="M12 3l1.9 4.8L18.8 9.7l-4.9 1.5L12 16l-1.9-4.8L5.2 9.7l4.9-1.9z"/></svg>
          </div>
          {!collapsed && <span className="font-semibold tracking-tight text-base">Lite-AI</span>}
        </div>

        <nav className="p-3.5 space-y-1 flex-1">
          {NAV.map(item => (
            <div key={item.to}>
              {item.group && !collapsed && (
                <p className="px-3 pt-4 pb-1.5 text-[11px] font-semibold text-slate-400 uppercase tracking-wider first:pt-2">{item.group}</p>
              )}
              <NavLink
                to={item.to}
                title={item.label}
                className={({ isActive }) =>
                  `${navItemBase} ${collapsed ? 'justify-center px-2' : ''} ` +
                  (isActive
                    ? 'bg-[#EEF0FF] text-[#4F46E5] font-semibold'
                    : 'text-slate-600 hover:bg-slate-50')
                }
              >
                {item.icon}
                {!collapsed && <span>{item.label}</span>}
              </NavLink>
            </div>
          ))}
        </nav>

        <div className="p-3 border-t border-slate-100 flex items-center gap-2">
          <button
            onClick={() => setCollapsed(c => !c)}
            aria-label="折叠"
            className="p-1.5 rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-600 shrink-0"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="1.8" viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/><path d="M14 9l-2 3 2 3"/></svg>
          </button>
          {!collapsed && <span className="text-[11px] text-slate-400">v0.1 · 数据域</span>}
        </div>
      </aside>

      <main className="flex-1 min-w-0">
        <header className="h-16 sticky top-0 z-20 bg-white/85 backdrop-blur border-b border-slate-200/70 flex items-center gap-3 px-7">
          <div className="ml-auto flex items-center gap-3">
            <button
              onClick={logout}
              className="text-sm text-red-600 hover:bg-slate-50 rounded-xl px-3 py-1.5"
            >
              登出
            </button>
          </div>
        </header>

        <div className="p-7">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
