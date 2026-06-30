import { useCallback, useEffect, useState } from 'react'
import { listLibraryAgents, type LibraryAgent } from '../api/omnigent'
import { useOrgs } from '../auth/useOrgs'
import { CreateAgentModal } from './CreateAgentModal'

// 智能体库页(US1/US2 · ADR-027)。列出本企业可见智能体(全局内置模板 + 本企业创建),
// 每条带 内置/本企业 徽标。企业管理员额外见「新建智能体」入口(非管理员无入口 +
// 服务端 can() 兜底 403,不靠前端藏按钮)。
// 列表来自 BFF GET /v1/ws/agents(已按企业过滤 + 剥前缀):
//   { data: [{ id, name, harness, description, builtin, enterprise_owned }, ...] }
// 视觉照数据集页(靛蓝 #6366F1)。

// 是否为本企业管理员:任一 membership.role === 'enterprise-admin'(v1 单企业)。
// 仅 UX 门——服务端对创建接口独立强制(red line)。
function isEnterpriseAdmin(orgs: ReturnType<typeof useOrgs>['orgs']): boolean {
  return !!orgs?.memberships?.some(m => m.role === 'enterprise-admin')
}

function dash(v: string | null | undefined): string {
  return v === null || v === undefined || v === '' ? '—' : String(v)
}

export function Agents() {
  const [agents, setAgents] = useState<LibraryAgent[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [showCreate, setShowCreate] = useState(false)
  const { orgs } = useOrgs()
  const canCreate = isEnterpriseAdmin(orgs)

  const load = useCallback(() => {
    return listLibraryAgents()
      .then(setAgents)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { void load() }, [load])

  return (
    <div>
      <div className="flex items-center gap-3 mb-4">
        <div>
          <h1 className="text-lg font-semibold text-slate-800">智能体库</h1>
          <p className="text-sm text-slate-500 mt-0.5">本企业可见的智能体:平台内置模板 + 本企业创建。对话开始时从中选用。</p>
        </div>
        {/* 仅企业管理员见入口(非管理员无按钮;服务端独立强制) */}
        {canCreate && (
          <button
            onClick={() => setShowCreate(true)}
            className="ml-auto bg-[#6366F1] hover:bg-[#4F46E5] text-white text-sm font-medium px-4 py-2.5 rounded-xl flex items-center gap-2 transition-colors"
          >
            <svg className="w-[18px] h-[18px]" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14" /></svg>
            新建智能体
          </button>
        )}
      </div>

      <div className="bg-white border border-slate-200/70 rounded-2xl overflow-hidden shadow-sm">
        <table className="w-full text-sm">
          <thead className="bg-slate-50/70 text-slate-500 text-xs">
            <tr className="text-left">
              <th className="font-medium px-5 py-3">名称</th>
              <th className="font-medium px-5 py-3">来源</th>
              <th className="font-medium px-5 py-3">基底</th>
              <th className="font-medium px-5 py-3">描述</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {loading && (
              <tr><td colSpan={4} className="px-5 py-8 text-center text-slate-400">加载中…</td></tr>
            )}
            {!loading && error && (
              <tr><td colSpan={4} className="px-5 py-8 text-center text-red-500">加载失败:{error}</td></tr>
            )}
            {!loading && !error && agents.length === 0 && (
              <tr><td colSpan={4} className="px-5 py-8 text-center text-slate-400">暂无可用智能体</td></tr>
            )}
            {!loading && !error && agents.map(a => (
              <tr key={a.id} className="hover:bg-slate-50">
                <td className="px-5 py-3">
                  <span className="font-medium text-[#4F46E5]">{a.name}</span>
                </td>
                <td className="px-5 py-3">
                  {a.enterprise_owned
                    ? <span className="text-[11px] font-medium text-[#4F46E5] bg-[#EEF0FF] rounded px-1.5 py-0.5">本企业</span>
                    : a.builtin
                      ? <span className="text-[11px] font-medium text-slate-500 bg-slate-100 rounded px-1.5 py-0.5">内置</span>
                      : <span className="text-slate-400">—</span>}
                </td>
                <td className="px-5 py-3 text-slate-500">{dash(a.harness)}</td>
                <td className="px-5 py-3 text-slate-600">{dash(a.description)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {showCreate && (
        <CreateAgentModal
          onClose={() => setShowCreate(false)}
          onDone={() => { setShowCreate(false); setLoading(true); setError(''); void load() }}
        />
      )}
    </div>
  )
}
