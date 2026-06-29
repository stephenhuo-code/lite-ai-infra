import { useEffect, useState } from 'react'
import { AgentChat } from './devws/AgentChat'
import { useSessionStream } from './devws/useSessionStream'
import { listAgents, listSessions, createSession, sendTurn, DEFAULT_AGENT_ID, type Session } from '../api/omnigent'

// Workspace 对话页(Plan 9a · Task T5)。左侧会话列表(新建 + 切换),右侧单个对话窗。
// 全经 BFF 同源 /v1/ws/*(会话 cookie + CSRF);前端不持 omnigent token。
// UX 取舍:进页拉用户自己的会话;不自动建会话(空态显引导,由用户点「新会话」建,
// 避免每次进页都凭空造 managed 容器);会话标题取 title,缺省回退短 id。
const BRAND = '#6366F1'

function sessionLabel(s: Session): string {
  return s.title?.trim() || `会话 ${s.id.slice(0, 8)}`
}

export function Workspace() {
  const [sessions, setSessions] = useState<Session[]>([])
  const [current, setCurrent] = useState<string | null>(null)
  const [agentId, setAgentId] = useState<string>(DEFAULT_AGENT_ID)
  const [creating, setCreating] = useState(false)
  const { items, addUser } = useSessionStream(current)

  // 进页:拉默认 agent(claude-native-ui)+ 用户自己的会话。
  useEffect(() => {
    listAgents()
      .then(ags => {
        const preferred = ags.find(a => a.name === 'claude-native-ui') ?? ags[0]
        if (preferred) setAgentId(preferred.id)
      })
      .catch(() => {})
    listSessions().then(setSessions).catch(() => {})
  }, [])

  async function newSession() {
    if (creating) return
    setCreating(true)
    try {
      const s = await createSession(agentId)
      if (s.id) {
        setSessions(prev => [s, ...prev.filter(x => x.id !== s.id)])
        setCurrent(s.id)
      }
    } catch { /* best-effort:建会话失败保持当前态 */ } finally {
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
            onClick={newSession}
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
          {sessions.map(s => (
            <button
              key={s.id}
              onClick={() => setCurrent(s.id)}
              className={`w-full text-left text-sm px-3 py-2 rounded-xl truncate transition-colors ${
                current === s.id ? 'bg-[#EEF0FF] text-[#4F46E5] font-medium' : 'text-slate-600 hover:bg-slate-50'
              }`}
              title={sessionLabel(s)}
            >
              {sessionLabel(s)}
            </button>
          ))}
        </nav>
      </aside>

      {/* 对话窗 */}
      <section className="flex-1 min-w-0 bg-slate-50 border border-slate-200/70 rounded-2xl overflow-hidden">
        {current ? (
          <AgentChat items={items} onSend={onSend} />
        ) : (
          <div className="h-full grid place-items-center text-center px-6">
            <div>
              <div className="mx-auto mb-4 h-14 w-14 rounded-2xl bg-[#EEF0FF] grid place-items-center" style={{ color: BRAND }}>
                <svg className="w-7 h-7" fill="none" stroke="currentColor" strokeWidth="1.7" viewBox="0 0 24 24"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" /></svg>
              </div>
              <h2 className="text-lg font-semibold text-slate-800">选择或新建一个会话</h2>
              <p className="text-sm text-slate-500 mt-2">在左侧选一个已有会话,或点「新会话」开始和 agent 对话。</p>
            </div>
          </div>
        )}
      </section>
    </div>
  )
}
