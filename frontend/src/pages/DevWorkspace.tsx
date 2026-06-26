import { useRef, useState } from 'react'
import { LeftTree } from './devws/LeftTree'

// Dev Workspace 页(plan 9b · US1/US2):左树 + 中 Agent 对话 + 右 文件/终端。
// 对话流(Task 5)/ 文件·终端(Task 6)依赖 omnigent stream schema(Task0 探针),此处为外壳 +
// 可拖拽分隔 + 右栏可收起(照高保真原型)。数据经 BFF 反代(api/devws.ts,best-effort)。
export function DevWorkspace() {
  const [rightW, setRightW] = useState(440)
  const [collapsed, setCollapsed] = useState(false)
  const rowRef = useRef<HTMLDivElement>(null)
  const dragging = useRef(false)

  function onMove(e: React.MouseEvent) {
    if (!dragging.current || !rowRef.current) return
    const rect = rowRef.current.getBoundingClientRect()
    const w = Math.max(340, Math.min(rect.width - 380, rect.right - e.clientX))
    setRightW(w)
  }

  return (
    <div ref={rowRef} className="flex h-[calc(100vh-3.5rem)] select-none"
         onMouseMove={onMove} onMouseUp={() => (dragging.current = false)}>
      {/* 左树 */}
      <aside className="w-72 shrink-0 border-r border-slate-200/70 overflow-y-auto px-2 py-3 bg-white">
        <LeftTree workingFiles={[]} datasets={[]} gitChanges={[]} onSelectDataset={() => {}} />
      </aside>

      {/* 中:Agent 对话(Task 5 接入 stream)*/}
      <section className="flex-1 min-w-0 grid place-items-center text-slate-400 text-sm">
        Agent 对话(接 omnigent stream:Task 5 / 待探针 schema)
      </section>

      {/* 拖拽分隔 + 右栏 */}
      {!collapsed ? (
        <>
          <div onMouseDown={() => (dragging.current = true)}
               className="w-1.5 shrink-0 cursor-col-resize bg-slate-200/70 hover:bg-[#6366F1]/60" />
          <section className="shrink-0 flex flex-col bg-white border-l border-slate-200/70"
                   style={{ width: rightW, minWidth: 340 }}>
            <div className="h-10 shrink-0 border-b border-slate-200/70 flex items-center px-3 text-[13px] text-slate-500">
              文件 / 终端 / 数据预览
              <button onClick={() => setCollapsed(true)} title="收起"
                      className="ml-auto p-1.5 rounded-lg text-slate-400 hover:text-[#6366F1] hover:bg-slate-50 cursor-pointer">›</button>
            </div>
            <div className="flex-1 grid place-items-center text-slate-400 text-sm">
              文件查看 / 终端(Task 6 / 待探针)
            </div>
          </section>
        </>
      ) : (
        <button onClick={() => setCollapsed(false)} title="展开 文件/终端"
                className="w-9 shrink-0 border-l border-slate-200/70 bg-white hover:bg-slate-50 text-slate-400 hover:text-[#6366F1] cursor-pointer">‹</button>
      )}
    </div>
  )
}
