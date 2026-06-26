import { useEffect, useRef, useState } from 'react'
import { LeftTree } from './devws/LeftTree'
import { AgentChat } from './devws/AgentChat'
import { useSessionStream } from './devws/useSessionStream'
import { createWorkspaceSession, resolveElicitation, sendTurn } from '../api/devws'

// Dev Workspace 页(plan 9b · US1/US2):左树 + 中 Agent 对话(SSE 流)+ 右 文件/终端(Task6/待依赖)。
// 对话流经 BFF 反代 omnigent(探针 RESULTS 9b);拖拽分隔 + 右栏可收起(照高保真原型)。
export function DevWorkspace() {
  const [rightW, setRightW] = useState(440)
  const [collapsed, setCollapsed] = useState(false)
  const [sid, setSid] = useState<string | null>(null)
  const rowRef = useRef<HTMLDivElement>(null)
  const dragging = useRef(false)
  const { items, addUser } = useSessionStream(sid)

  useEffect(() => {
    createWorkspaceSession().then(s => setSid(s.session_id)).catch(() => {})
  }, [])

  function onMove(e: React.MouseEvent) {
    if (!dragging.current || !rowRef.current) return
    const rect = rowRef.current.getBoundingClientRect()
    setRightW(Math.max(340, Math.min(rect.width - 380, rect.right - e.clientX)))
  }
  function onSend(text: string) { addUser(text); if (sid) sendTurn(sid, text).catch(() => {}) }
  function onResolve(id: string, approve: boolean) { if (sid) resolveElicitation(sid, id, approve).catch(() => {}) }

  return (
    <div ref={rowRef} className="flex h-[calc(100vh-3.5rem)] select-none"
         onMouseMove={onMove} onMouseUp={() => (dragging.current = false)}>
      <aside className="w-72 shrink-0 border-r border-slate-200/70 overflow-y-auto px-2 py-3 bg-white">
        <LeftTree workingFiles={[]} datasets={[]} gitChanges={[]} onSelectDataset={() => {}} />
      </aside>

      <section className="flex-1 min-w-0 border-r border-slate-200/70">
        <AgentChat items={items} onSend={onSend} onResolve={onResolve} />
      </section>

      {!collapsed ? (
        <>
          <div onMouseDown={() => (dragging.current = true)}
               className="w-1.5 shrink-0 cursor-col-resize bg-slate-200/70 hover:bg-[#6366F1]/60" />
          <section className="shrink-0 flex flex-col bg-white" style={{ width: rightW, minWidth: 340 }}>
            <div className="h-10 shrink-0 border-b border-slate-200/70 flex items-center px-3 text-[13px] text-slate-500">
              文件 / 终端 / 数据预览
              <button onClick={() => setCollapsed(true)} title="收起"
                      className="ml-auto p-1.5 rounded-lg text-slate-400 hover:text-[#6366F1] hover:bg-slate-50 cursor-pointer">›</button>
            </div>
            <div className="flex-1 grid place-items-center text-slate-400 text-sm">文件查看 / 终端(Task 6)</div>
          </section>
        </>
      ) : (
        <button onClick={() => setCollapsed(false)} title="展开 文件/终端"
                className="w-9 shrink-0 border-l border-slate-200/70 bg-white hover:bg-slate-50 text-slate-400 hover:text-[#6366F1] cursor-pointer">‹</button>
      )}
    </div>
  )
}
