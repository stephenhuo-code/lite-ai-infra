import { useState } from 'react'
import type { ChatItem } from './useSessionStream'

// Workspace 对话窗(Plan 9a)。气泡(user/assistant)+ composer。视觉照品牌 #6366F1。
// 9a = 纯文本对话:无 tool 卡 / ask 审批卡 / can() —— 那些是 9b,本页一律不渲染。
const BRAND = '#6366F1'

export interface AgentChatProps {
  items: ChatItem[]
  onSend: (text: string) => void
  disabled?: boolean
}

export function AgentChat({ items, onSend, disabled }: AgentChatProps) {
  const [text, setText] = useState('')
  function send() {
    const t = text.trim()
    if (t && !disabled) { onSend(t); setText('') }
  }
  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-y-auto px-5 py-5 space-y-3">
        {items.map((it, i) =>
          it.kind === 'user' ? (
            <div key={i} className="flex justify-end">
              <div className="max-w-[80%] text-white rounded-2xl rounded-tr-sm px-4 py-2.5 text-sm whitespace-pre-wrap" style={{ background: BRAND }}>{it.text}</div>
            </div>
          ) : (
            <div key={i} className="max-w-[82%] bg-white border border-slate-200 rounded-2xl rounded-tl-sm px-4 py-3 text-sm shadow-sm whitespace-pre-wrap">{it.text}</div>
          )
        )}
      </div>
      <div className="shrink-0 border-t border-slate-200/70 bg-white px-4 py-3">
        <div className="flex items-end gap-2 border border-slate-200 rounded-2xl px-3 py-2 focus-within:border-[#6366F1]">
          <textarea
            rows={1} value={text} onChange={e => setText(e.target.value)}
            // Enter 发送,但避开中文输入法合成期(选词回车不发送);Shift+Enter 换行。
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send() } }}
            placeholder="给 agent 发条消息…"
            className="flex-1 resize-none outline-none text-sm py-1.5 bg-transparent" />
          <button onClick={send} disabled={disabled} className="text-white text-sm font-medium px-3.5 py-1.5 rounded-xl cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed" style={{ background: BRAND }}>发送</button>
        </div>
        <p className="text-[10px] text-slate-400 mt-1.5 px-1">回复以会话历史为准 · 流式预览为尽力而为</p>
      </div>
    </div>
  )
}
