import { useEffect, useRef, useState } from 'react'
import { LeftTree } from './devws/LeftTree'
import { AgentChat } from './devws/AgentChat'
import { RightPane } from './devws/RightPane'
import { useSessionStream } from './devws/useSessionStream'
import { createWorkspaceSession, fetchGitChanges, fetchWorkingFiles, resolveElicitation, sendTurn } from '../api/devws'
import { listDatasets, type Dataset } from '../api/catalog'

// Dev Workspace 页(plan 9b · US1/US2):左树(真实 catalog 数据集 + 工作目录 + git)+ 中 Agent 对话(SSE)
// + 右 文件(monaco)/终端(xterm)/数据预览。对话流经 BFF 反代 omnigent;拖拽分隔 + 右栏可收起。
export function DevWorkspace() {
  const [rightW, setRightW] = useState(440)
  const [collapsed, setCollapsed] = useState(false)
  const [sid, setSid] = useState<string | null>(null)
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [workingFiles, setWorkingFiles] = useState<string[]>([])
  const [gitChanges, setGitChanges] = useState<{ x: string; path: string }[]>([])
  const [preview, setPreview] = useState<string | undefined>(undefined)
  const rowRef = useRef<HTMLDivElement>(null)
  const dragging = useRef(false)
  const { items, addUser } = useSessionStream(sid)

  useEffect(() => { createWorkspaceSession().then(s => setSid(s.session_id)).catch(() => {}) }, [])
  useEffect(() => { listDatasets('data', 'datasets').then(r => setDatasets(r.datasets ?? [])).catch(() => {}) }, [])
  useEffect(() => { fetchWorkingFiles().then(setWorkingFiles).catch(() => {}); fetchGitChanges().then(setGitChanges).catch(() => {}) }, [sid])

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
        <LeftTree
          workingFiles={workingFiles}
          datasets={datasets.map(d => ({ name: d.name, kind: d.kind ?? undefined }))}
          gitChanges={gitChanges}
          onSelectDataset={setPreview} />
      </aside>

      <section className="flex-1 min-w-0 border-r border-slate-200/70">
        <AgentChat items={items} onSend={onSend} onResolve={onResolve} />
      </section>

      {!collapsed ? (
        <>
          <div onMouseDown={() => (dragging.current = true)}
               className="w-1.5 shrink-0 cursor-col-resize bg-slate-200/70 hover:bg-[#6366F1]/60" />
          <section className="shrink-0" style={{ width: rightW, minWidth: 340 }}>
            <RightPane fileContent="" termLines={[]} previewName={preview} onCollapse={() => setCollapsed(true)} />
          </section>
        </>
      ) : (
        <button onClick={() => setCollapsed(false)} title="展开 文件/终端"
                className="w-9 shrink-0 border-l border-slate-200/70 bg-white hover:bg-slate-50 text-slate-400 hover:text-[#6366F1] cursor-pointer">‹</button>
      )}
    </div>
  )
}
