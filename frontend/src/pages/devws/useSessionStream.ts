import { useEffect, useState } from 'react'
import { fetchSessionItems } from '../../api/devws'

// Dev Workspace 对话流(plan 9b)。live 实证:harness=claude-native 的回复只落 GET /items
// (SSE 不发 response.output_text.delta —— 那是 API-harness 才有的),故对话历史以 items 为权威源,
// SSE `/stream` 仅作"有变化→刷新 items"的触发器 + ASK(elicitation)即时卡片。
// applyStreamEvent/parseSse 保留(API-harness 的 delta 映射 + 单测),live 走 items 路径。
export type ChatItem =
  | { kind: 'user'; text: string }
  | { kind: 'assistant'; text: string }
  | { kind: 'tool'; name: string }
  | { kind: 'ask'; id: string; prompt: string }

export interface StreamEvent {
  type?: string
  delta?: string
  item?: { type?: string; name?: string }
  elicitation_id?: string
  message?: string
}

export function applyStreamEvent(items: ChatItem[], ev: StreamEvent): ChatItem[] {
  const t: string = ev?.type ?? ''
  if (t === 'response.output_text.delta') {
    const last = items[items.length - 1]
    if (last && last.kind === 'assistant') {
      return [...items.slice(0, -1), { kind: 'assistant', text: last.text + (ev.delta ?? '') }]
    }
    return [...items, { kind: 'assistant', text: ev.delta ?? '' }]
  }
  if (t === 'response.output_item.done' && ev.item?.type === 'function_call') {
    return [...items, { kind: 'tool', name: ev.item.name ?? '?' }]
  }
  if (t.includes('elicitation')) {
    return [...items, { kind: 'ask', id: ev.elicitation_id ?? '', prompt: ev.message ?? '' }]
  }
  return items   // lifecycle / heartbeat / unknown:忽略
}

// 解析 SSE 文本块为事件对象数组(data: 行 JSON)。
export function parseSse(buffer: string): StreamEvent[] {
  const out: StreamEvent[] = []
  for (const block of buffer.split('\n\n')) {
    const data = block.split('\n').filter(l => l.startsWith('data:')).map(l => l.slice(5).trim()).join('')
    if (data && data !== '[DONE]') {
      try { out.push(JSON.parse(data) as StreamEvent) } catch { /* 半包,忽略 */ }
    }
  }
  return out
}

// 去重连续相同的 user/assistant 气泡(乐观 user 与 refetch 重叠 / 后端漏网的回灌)。
export function dedupeChat(items: ChatItem[]): ChatItem[] {
  const out: ChatItem[] = []
  for (const it of items) {
    const last = out[out.length - 1]
    if (last && (it.kind === 'user' || it.kind === 'assistant') && last.kind === it.kind &&
        last.text === it.text) continue
    out.push(it)
  }
  return out
}

export function useSessionStream(sessionId: string | null): { items: ChatItem[]; addUser: (t: string) => void } {
  const [items, setItems] = useState<ChatItem[]>([])     // 权威:GET /items
  const [asks, setAsks] = useState<ChatItem[]>([])        // ASK 卡片:只在 SSE
  const addUser = (t: string) => setItems(prev => [...prev, { kind: 'user', text: t }])  // 乐观,refetch 会校正
  useEffect(() => {
    if (!sessionId) return            // sessionId 仅 null→sid 变一次(建会话),items/asks 初始即空,无需清
    const ctrl = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    const refetch = () => {
      clearTimeout(timer)
      timer = setTimeout(() => {
        fetchSessionItems(sessionId).then(raw => setItems(raw as ChatItem[])).catch(() => {})
      }, 400)
    }
    refetch()   // 进入会话先拉一次历史
    ;(async () => {
      const res = await fetch(`/v1/ws/sessions/${encodeURIComponent(sessionId)}/stream`,
        { headers: { Accept: 'text/event-stream' }, signal: ctrl.signal })
      if (!res.ok || !res.body) return
      const reader = res.body.getReader()
      const dec = new TextDecoder()
      let buf = ''
      for (;;) {
        const { value, done } = await reader.read()
        if (done) break
        buf += dec.decode(value, { stream: true })
        const parts = buf.split('\n\n')
        buf = parts.pop() ?? ''
        for (const ev of parseSse(parts.join('\n\n') + '\n\n')) {
          if ((ev.type ?? '').includes('elicitation'))     // ASK:即时卡片(不在 items)
            setAsks(prev => [...prev, { kind: 'ask', id: ev.elicitation_id ?? '', prompt: ev.message ?? '' }])
          else
            refetch()                                       // 任何生命周期变化 → 刷新 items
        }
      }
    })().catch(() => {})
    return () => { ctrl.abort(); clearTimeout(timer) }
  }, [sessionId])
  return { items: dedupeChat([...items, ...asks]), addUser }
}
