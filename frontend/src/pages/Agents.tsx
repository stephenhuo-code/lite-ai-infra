import { useCallback, useEffect, useState } from 'react'
import { listLibraryAgents, deleteAgent, type LibraryAgent } from '../api/omnigent'
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

// 单张智能体卡片(展示型)。圆角软卡 + 首字母头像 + 来源徽标 + 基底 + 描述(≤3 行)。
// 管理员操作(仅 UX 门,服务端对 PUT/DELETE 独立强制):本企业卡片可「编辑」+「删除」;
// 内置卡片(全局共享)无操作(不可就地改/删,避免影响其它企业)。
function AgentCard({ agent, canManage, onEdit, onDelete }: {
  agent: LibraryAgent
  canManage: boolean
  onEdit: (a: LibraryAgent) => void
  onDelete: (a: LibraryAgent) => void
}) {
  const initial = (agent.name?.trim()?.[0] ?? '?').toUpperCase()
  const ownEditable = canManage && agent.enterprise_owned === true && !agent.builtin
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm hover:shadow-md transition-shadow flex flex-col">
      <div className="flex items-start gap-3">
        {/* 首字母头像(品牌靛蓝),纯视觉 */}
        <div
          aria-hidden="true"
          className="shrink-0 w-10 h-10 rounded-xl bg-[#EEF0FF] text-[#4F46E5] font-semibold flex items-center justify-center"
        >
          {initial}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h2 className="font-semibold text-slate-800 truncate">{agent.name}</h2>
            {/* 来源徽标:本企业 = 品牌靛蓝;内置 = 中性 slate */}
            {agent.enterprise_owned
              ? <span className="shrink-0 text-[11px] font-medium text-[#4F46E5] bg-[#EEF0FF] rounded px-1.5 py-0.5">本企业</span>
              : agent.builtin
                ? <span className="shrink-0 text-[11px] font-medium text-slate-500 bg-slate-100 rounded px-1.5 py-0.5">内置</span>
                : null}
          </div>
          {/* 基底 harness:小号 mono 次要标签 */}
          <div className="mt-0.5 text-xs font-mono text-slate-400">{dash(agent.harness)}</div>
        </div>
        {/* 操作入口(右上,低调):仅本企业卡片 = 编辑/删除 */}
        {ownEditable && (
          <div className="shrink-0 flex items-center gap-1">
            <button
              onClick={() => onEdit(agent)}
              aria-label={`编辑 ${agent.name}`}
              className="text-xs font-medium text-slate-500 hover:text-[#4F46E5] px-2 py-1 rounded-lg hover:bg-[#EEF0FF] transition-colors"
            >
              编辑
            </button>
            <button
              onClick={() => onDelete(agent)}
              aria-label={`删除 ${agent.name}`}
              className="text-xs font-medium text-slate-500 hover:text-red-600 px-2 py-1 rounded-lg hover:bg-red-50 transition-colors"
            >
              删除
            </button>
          </div>
        )}
      </div>
      {/* 描述,≤3 行截断 */}
      <p className="mt-3 text-sm text-slate-600 line-clamp-3">{dash(agent.description)}</p>
    </div>
  )
}

// 加载态骨架卡(与卡片同尺寸,避免布局抖动)。
function SkeletonCard() {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm animate-pulse">
      <div className="flex items-start gap-3">
        <div className="shrink-0 w-10 h-10 rounded-xl bg-slate-100" />
        <div className="flex-1 space-y-2 pt-1">
          <div className="h-4 w-1/2 bg-slate-100 rounded" />
          <div className="h-3 w-1/3 bg-slate-100 rounded" />
        </div>
      </div>
      <div className="mt-3 space-y-2">
        <div className="h-3 w-full bg-slate-100 rounded" />
        <div className="h-3 w-4/5 bg-slate-100 rounded" />
      </div>
    </div>
  )
}

export function Agents() {
  const [agents, setAgents] = useState<LibraryAgent[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [showCreate, setShowCreate] = useState(false)
  const [editAgent, setEditAgent] = useState<LibraryAgent | null>(null)
  const { orgs } = useOrgs()
  const canCreate = isEnterpriseAdmin(orgs)

  const load = useCallback(() => {
    return listLibraryAgents()
      .then(setAgents)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { void load() }, [load])

  // 删除本企业智能体(二次确认)。失败(403/404)→ 顶部错误条,不静默。
  async function handleDelete(agent: LibraryAgent) {
    if (!window.confirm(`确认删除智能体「${agent.name}」?此操作不可撤销(仅删除本企业创建的智能体)。`)) return
    try {
      await deleteAgent(agent.id)
      setLoading(true); setError(''); void load()
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      setError(msg === '403' ? '你没有删除该智能体的权限(需企业管理员;内置/他企业不可删)。'
             : msg === '404' ? '该智能体已不存在。' : `删除失败:${msg}`)
    }
  }

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

      {/* 加载态:骨架卡网格 */}
      {loading && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {Array.from({ length: 6 }).map((_, i) => <SkeletonCard key={i} />)}
        </div>
      )}

      {/* 错误态:居中卡片提示 */}
      {!loading && error && (
        <div className="rounded-2xl border border-red-200 bg-red-50 p-8 text-center text-sm text-red-600">
          加载失败:{error}
        </div>
      )}

      {/* 空态:居中卡片提示 */}
      {!loading && !error && agents.length === 0 && (
        <div className="rounded-2xl border border-slate-200 bg-white p-12 text-center text-sm text-slate-400">
          暂无可用智能体
        </div>
      )}

      {/* 列表:响应式卡片网格(移动端单列) */}
      {!loading && !error && agents.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {agents.map(a => (
            <AgentCard key={a.id} agent={a} canManage={canCreate}
                       onEdit={setEditAgent} onDelete={handleDelete} />
          ))}
        </div>
      )}

      {showCreate && (
        <CreateAgentModal
          mode="create"
          onClose={() => setShowCreate(false)}
          onDone={() => { setShowCreate(false); setLoading(true); setError(''); void load() }}
        />
      )}

      {editAgent && (
        <CreateAgentModal
          mode="edit"
          agent={editAgent}
          onClose={() => setEditAgent(null)}
          onDone={() => { setEditAgent(null); setLoading(true); setError(''); void load() }}
        />
      )}
    </div>
  )
}
