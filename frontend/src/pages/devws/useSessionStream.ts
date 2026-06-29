import { useEffect, useState } from 'react'
import { fetchSessionItems } from '../../api/omnigent'

// Workspace 对话流(Plan 9a)。live 实证(P1 探针):harness=claude-native + 共享订阅,
// `response.output_text.delta` best-effort、消息块级、可能滞后于 `response.completed` 才到。
// 故:(1) 读流别在 completed 停,读到流关闭(body 结束)为止;
//     (2) 对话历史以 GET /items 为权威源,SSE 既作渐进预览(应用 output_text.delta)
//         又作"有变化→刷新 items"的触发器。9a 无 tool/ask —— 纯 user/assistant 气泡。
export type ChatItem =
  | { kind: 'user'; text: string }
  | { kind: 'assistant'; text: string }

export interface StreamEvent {
  type?: string
  delta?: string
}

// 应用单个流事件到当前气泡列表 —— 9a 只处理 output_text.delta(渐进预览)。
// delta 追加到末尾的 assistant 气泡;若末尾不是 assistant 则起一个新 assistant 气泡。
export function applyStreamEvent(items: ChatItem[], ev: StreamEvent): ChatItem[] {
  const t: string = ev?.type ?? ''
  if (t === 'response.output_text.delta') {
    const last = items[items.length - 1]
    if (last && last.kind === 'assistant') {
      return [...items.slice(0, -1), { kind: 'assistant', text: last.text + (ev.delta ?? '') }]
    }
    return [...items, { kind: 'assistant', text: ev.delta ?? '' }]
  }
  return items   // 生命周期 / 心跳 / 未知:忽略
}

// 解析 SSE 文本块为事件对象数组(data: 行 JSON)。半包(JSON 不完整)忽略。
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
    if (last && last.kind === it.kind && last.text === it.text) continue
    out.push(it)
  }
  return out
}

export function useSessionStream(sessionId: string | null): { items: ChatItem[]; addUser: (t: string) => void } {
  const [items, setItems] = useState<ChatItem[]>([])      // 权威:GET /items
  const [preview, setPreview] = useState<ChatItem[]>([])  // SSE 渐进预览(output_text.delta)
  const addUser = (t: string) => setItems(prev => [...prev, { kind: 'user', text: t }])  // 乐观,refetch 会校正

  useEffect(() => {
    if (!sessionId) return
    const ctrl = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    const refetch = () => {
      clearTimeout(timer)
      timer = setTimeout(() => {
        fetchSessionItems(sessionId)
          .then(next => { setItems(next); setPreview([]) })   // 权威到货 → 清渐进预览
          .catch(() => {})
      }, 400)
    }
    refetch()   // 进入会话先拉一次历史
    ;(async () => {
      const res = await fetch(`/v1/ws/sessions/${encodeURIComponent(sessionId)}/stream`,
        { headers: { Accept: 'text/event-stream' }, credentials: 'include', signal: ctrl.signal })
      if (!res.ok || !res.body) return
      const reader = res.body.getReader()
      const dec = new TextDecoder()
      let buf = ''
      // 读到流关闭为止 —— 绝不在 response.completed 处停(delta 可能在 completed 之后才到)。
      for (;;) {
        const { value, done } = await reader.read()
        if (done) break
        buf += dec.decode(value, { stream: true })
        const parts = buf.split('\n\n')
        buf = parts.pop() ?? ''
        for (const ev of parseSse(parts.join('\n\n') + '\n\n')) {
          if ((ev.type ?? '') === 'response.output_text.delta')
            setPreview(prev => applyStreamEvent(prev, ev))   // 渐进预览
          refetch()                                          // 任何事件 → 触发刷新 items(权威)
        }
      }
    })().catch(() => {})
    // 清理(切会话/卸载):中止上游流 + 清掉旧会话的气泡(避免切换瞬间残留上一个会话内容)。
    return () => { ctrl.abort(); clearTimeout(timer); setItems([]); setPreview([]) }
  }, [sessionId])

  return { items: dedupeChat([...items, ...preview]), addUser }
}
