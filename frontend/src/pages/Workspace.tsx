import { useEffect, useMemo, useState } from 'react'
import { AgentChat } from './devws/AgentChat'
import { useSessionStream } from './devws/useSessionStream'
import { listLibraryAgents, listSessions, createSession, sendTurn, type LibraryAgent, type Session } from '../api/omnigent'

// Workspace 对话页(Plan 9a · Task T5 + 智能体库 ADR-027)。左侧会话列表(新建 + 切换),
// 右侧单个对话窗。全经 BFF 同源 /v1/ws/*(会话 cookie + CSRF);前端不持 omnigent token。
// 智能体库:新建会话时先从库里【选一个智能体】(替换原写死默认),选定后建会话;
// 会话创建后【锁定】到该智能体——界面无"换智能体"入口(BFF 也不暴露 switch-agent)。
// UX:进页拉用户自己的会话 + 库智能体;空态显引导,由用户点「新会话」→ 选智能体 → 建。
const BRAND = '#6366F1'

function sessionLabel(s: Session): string {
  return s.title?.trim() || `会话 ${s.id.slice(0, 8)}`
}

// 默认预选:优先 claude-native-ui 内置模板,否则第一个 builtin,否则第一个。
function pickDefault(agents: LibraryAgent[]): string {
  const preferred = agents.find(a => a.name === 'claude-native-ui')
    ?? agents.find(a => a.builtin)
    ?? agents[0]
  return preferred?.id ?? ''
}

export function Workspace() {
  const [sessions, setSessions] = useState<Session[]>([])
  const [current, setCurrent] = useState<string | null>(null)
  const [agents, setAgents] = useState<LibraryAgent[]>([])
  // 选择器选中的 agentId(新会话用);进页用默认预选(库加载后填)。
  const [selectedAgent, setSelectedAgent] = useState<string>('')
  // 已创建会话 → 其绑定的智能体(锁定,仅展示,不可改)。
  const [sessionAgent, setSessionAgent] = useState<Record<string, LibraryAgent | undefined>>({})
  const [picking, setPicking] = useState(false) // 是否在显示智能体选择器
  const [creating, setCreating] = useState(false)
  const [pickErr, setPickErr] = useState('') // 建会话失败 → 明确反馈(不静默卡死)
  const { items, addUser } = useSessionStream(current)

  // 进页:拉库智能体(供选择器 + 默认预选)+ 用户自己的会话。
  useEffect(() => {
    listLibraryAgents()
      .then(ags => {
        setAgents(ags)
        setSelectedAgent(prev => prev || pickDefault(ags))
      })
      .catch(() => {})
    listSessions().then(setSessions).catch(() => {})
  }, [])

  const agentById = useMemo(() => {
    const m = new Map<string, LibraryAgent>()
    for (const a of agents) m.set(a.id, a)
    return m
  }, [agents])

  // 当前会话绑定的智能体(展示用;锁定)。
  const currentAgent = current ? sessionAgent[current] : undefined

  function openPicker() {
    if (creating) return
    setSelectedAgent(prev => prev || pickDefault(agents))
    setPickErr('')
    setPicking(true)
  }

  // BFF 错误 → 大白话提示(api.post 失败时抛 Error(`${status}`))。
  function sessionErrMessage(e: unknown): string {
    const msg = e instanceof Error ? e.message : String(e)
    if (msg === '403') return '无法用该智能体建会话(无权限或它不属于本企业),请换一个再试。'
    if (msg === '404') return '该智能体已不可用,请刷新后换一个再试。'
    return `建会话失败(${msg}),请重试或换一个智能体。`
  }

  async function confirmNewSession() {
    if (creating || !selectedAgent) return
    setCreating(true)
    setPickErr('')
    try {
      const s = await createSession(selectedAgent)
      if (!s.id) throw new Error('empty')   // 没拿到 id = 半成品,显式失败不静默
      setSessions(prev => [s, ...prev.filter(x => x.id !== s.id)])
      setSessionAgent(prev => ({ ...prev, [s.id]: agentById.get(selectedAgent) }))
      setCurrent(s.id)
      setPicking(false)
    } catch (e) {
      // 建会话失败:明确反馈、保持选择器开着、按钮可重试,不残留半成品会话(spec Edge Case)。
      setPickErr(sessionErrMessage(e))
    } finally {
      setCreating(false)
    }
  }

  function onSend(text: string) {
    if (!current) return
    addUser(text)                  // 乐观加 user 气泡(refetch 会校正)
    sendTurn(current, text).catch(() => {})
  }

  return (
    <div className="flex h-[calc(100vh-7rem)] gap-4">
      {/* 会话列表 */}
      <aside className="w-64 shrink-0 bg-white border border-slate-200/70 rounded-2xl flex flex-col overflow-hidden">
        <div className="p-3 border-b border-slate-100">
          <button
            onClick={openPicker}
            disabled={creating}
            className="w-full text-white text-sm font-medium px-3 py-2 rounded-xl cursor-pointer disabled:opacity-50"
            style={{ background: BRAND }}
          >
            {creating ? '创建中…' : '+ 新会话'}
          </button>
        </div>
        <nav className="flex-1 overflow-y-auto p-2 space-y-1">
          {sessions.length === 0 && (
            <p className="text-xs text-slate-400 px-2 py-3">还没有会话,点上方「新会话」开始。</p>
          )}
          {sessions.map(s => {
            const a = sessionAgent[s.id]
            return (
              <button
                key={s.id}
                onClick={() => setCurrent(s.id)}
                className={`w-full text-left text-sm px-3 py-2 rounded-xl truncate transition-colors ${
                  current === s.id ? 'bg-[#EEF0FF] text-[#4F46E5] font-medium' : 'text-slate-600 hover:bg-slate-50'
                }`}
                title={sessionLabel(s)}
              >
                <span className="block truncate">{sessionLabel(s)}</span>
                {a && <span className="block text-[11px] text-slate-400 truncate">{a.name}</span>}
              </button>
            )
          })}
        </nav>
      </aside>

      {/* 对话窗 */}
      <section className="flex-1 min-w-0 bg-slate-50 border border-slate-200/70 rounded-2xl overflow-hidden flex flex-col">
        {current ? (
          <>
            {/* 会话绑定的智能体(锁定展示,无"换智能体"入口) */}
            {currentAgent && (
              <div className="px-5 py-2.5 border-b border-slate-200/70 bg-white/70 flex items-center gap-2 text-sm">
                <span className="text-slate-400">智能体</span>
                <span className="font-medium text-slate-700">{currentAgent.name}</span>
                <span className="text-[11px] text-slate-400 bg-slate-100 rounded px-1.5 py-0.5">已锁定</span>
              </div>
            )}
            <div className="flex-1 min-h-0">
              <AgentChat items={items} onSend={onSend} />
            </div>
          </>
        ) : (
          <div className="h-full grid place-items-center text-center px-6">
            <div>
              <div className="mx-auto mb-4 h-14 w-14 rounded-2xl bg-[#EEF0FF] grid place-items-center" style={{ color: BRAND }}>
                <svg className="w-7 h-7" fill="none" stroke="currentColor" strokeWidth="1.7" viewBox="0 0 24 24"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" /></svg>
              </div>
              <h2 className="text-lg font-semibold text-slate-800">选择或新建一个会话</h2>
              <p className="text-sm text-slate-500 mt-2">在左侧选一个已有会话,或点「新会话」从智能体库选一个智能体开始对话。</p>
            </div>
          </div>
        )}
      </section>

      {/* 智能体选择器:新建会话前选一个智能体(选定后建会话,会话锁定到它) */}
      {picking && (
        <div className="fixed inset-0 z-40 grid place-items-center px-4">
          <div className="absolute inset-0 bg-slate-900/30 backdrop-blur-[2px]" onClick={() => !creating && setPicking(false)} />
          <div className="relative bg-white w-full max-w-md rounded-2xl shadow-xl border border-slate-200 p-6">
            <div className="flex items-center justify-between mb-1">
              <h2 className="font-semibold text-lg">选择智能体</h2>
              <button onClick={() => !creating && setPicking(false)} aria-label="关闭" className="text-slate-400 hover:text-slate-700">
                <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path d="M18 6L6 18M6 6l12 12" /></svg>
              </button>
            </div>
            <p className="text-sm text-slate-500 mb-4">该会话将固定用此智能体,开始后不可更换。</p>

            <label className="block text-xs font-medium text-slate-600 mb-1.5" htmlFor="ws-agent">智能体</label>
            <select
              id="ws-agent"
              aria-label="选择智能体"
              value={selectedAgent}
              onChange={e => setSelectedAgent(e.target.value)}
              className="w-full rounded-xl border border-slate-300 px-3.5 py-2.5 text-sm focus:border-[#6366F1] outline-none bg-white"
            >
              {agents.length === 0 && <option value="">(暂无可用智能体)</option>}
              {agents.map(a => (
                <option key={a.id} value={a.id}>
                  {a.name}{a.enterprise_owned ? '(本企业)' : a.builtin ? '(内置)' : ''}
                </option>
              ))}
            </select>

            {pickErr && (
              <div role="alert" className="mt-3.5 text-sm text-red-700 bg-red-50 border border-red-200 rounded-xl px-3.5 py-2.5">
                {pickErr}
              </div>
            )}

            <div className="flex justify-end gap-2 mt-6">
              <button
                onClick={() => setPicking(false)}
                disabled={creating}
                className="text-sm text-slate-600 px-4 py-2.5 rounded-xl hover:bg-slate-100 disabled:opacity-50"
              >
                取消
              </button>
              <button
                onClick={confirmNewSession}
                disabled={creating || !selectedAgent}
                className="text-sm font-medium text-white bg-[#6366F1] hover:bg-[#4F46E5] px-4 py-2.5 rounded-xl disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {creating ? '创建中…' : '开始对话'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
