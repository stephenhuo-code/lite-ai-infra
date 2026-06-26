import { useEffect, useState } from 'react'

// Dev Workspace 对话流(plan 9b · 探针 RESULTS 9b②)。SSE `/v1/ws/sessions/{id}/stream`(经 BFF 透传)
// 逐条 ServerStreamEvent → ChatItem。事件 type 取 OpenAI-responses 约定(omnigent 镜像);
// 精确 discriminator 以 live(RUNBOOK)为准,差异只改本文件的 mapping 一处。
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

export function useSessionStream(sessionId: string | null): { items: ChatItem[]; addUser: (t: string) => void } {
  const [items, setItems] = useState<ChatItem[]>([])
  const addUser = (t: string) => setItems(prev => [...prev, { kind: 'user', text: t }])
  useEffect(() => {
    if (!sessionId) return
    const ctrl = new AbortController()
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
          setItems(prev => applyStreamEvent(prev, ev))
        }
      }
    })().catch(() => {})
    return () => ctrl.abort()
  }, [sessionId])
  return { items, addUser }
}
