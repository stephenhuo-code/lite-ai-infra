import { useState } from 'react'
import type { ChatItem } from './useSessionStream'

// Dev Workspace 对话窗(plan 9b · US1/US2)。气泡 / 工具卡(can() 经 MCP)/ ASK 审批卡 + composer。
// 视觉照高保真原型(brand #6366F1)。
const BRAND = '#6366F1'

export interface AgentChatProps {
  items: ChatItem[]
  onSend: (text: string) => void
  onResolve: (elicitationId: string, approve: boolean) => void
}

export function AgentChat({ items, onSend, onResolve }: AgentChatProps) {
  const [text, setText] = useState('')
  function send() {
    const t = text.trim()
    if (t) { onSend(t); setText('') }
  }
  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-y-auto px-5 py-5 space-y-3">
        {items.map((it, i) => {
          if (it.kind === 'user')
            return <div key={i} className="flex justify-end"><div className="max-w-[80%] text-white rounded-2xl rounded-tr-sm px-4 py-2.5 text-sm" style={{ background: BRAND }}>{it.text}</div></div>
          if (it.kind === 'assistant')
            return <div key={i} className="max-w-[82%] bg-white border border-slate-200 rounded-2xl rounded-tl-sm px-4 py-3 text-sm shadow-sm whitespace-pre-wrap">{it.text}</div>
          if (it.kind === 'tool')
            return <div key={i} className="max-w-[82%] rounded-xl border border-slate-200 bg-slate-50/70 px-3 py-2 text-[13px] flex items-center gap-2 font-mono"><span style={{ color: BRAND }}>⚙</span>{it.name}<span className="ml-auto text-emerald-600 text-xs">can() 通过</span></div>
          // ask
          return (
            <div key={i} className="max-w-[82%] rounded-xl border-2 border-amber-300 bg-amber-50/60 px-3.5 py-3 text-sm">
              <div className="text-amber-800 font-medium mb-2">需要确认(policy: ASK)</div>
              <div className="font-mono text-xs text-amber-900/80 mb-3">{it.prompt}</div>
              <div className="flex gap-2">
                <button onClick={() => onResolve(it.id, true)} className="bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-medium px-3.5 py-1.5 rounded-lg cursor-pointer">批准</button>
                <button onClick={() => onResolve(it.id, false)} className="border border-slate-300 text-slate-600 text-xs px-3.5 py-1.5 rounded-lg hover:bg-white cursor-pointer">拒绝</button>
              </div>
            </div>
          )
        })}
      </div>
      <div className="shrink-0 border-t border-slate-200/70 bg-white px-4 py-3">
        <div className="flex items-end gap-2 border border-slate-200 rounded-2xl px-3 py-2 focus-within:border-[#6366F1]">
          <textarea
            rows={1} value={text} onChange={e => setText(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send() } }}
            placeholder="让 agent 探查数据、写管线、改代码…"
            className="flex-1 resize-none outline-none text-sm py-1.5 bg-transparent" />
          <button onClick={send} className="text-white text-sm font-medium px-3.5 py-1.5 rounded-xl cursor-pointer" style={{ background: BRAND }}>发送</button>
        </div>
        <p className="text-[10px] text-slate-400 mt-1.5 px-1">agent 在沙箱内执行 · 数据访问经 can()(企业+owner)· 危险操作需确认</p>
      </div>
    </div>
  )
}
