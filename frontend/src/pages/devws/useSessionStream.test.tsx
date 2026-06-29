import { it, expect } from 'vitest'
import { parseSse, applyStreamEvent, dedupeChat, type ChatItem } from './useSessionStream'

// parseSse:多事件缓冲 + 半包(不完整 JSON)忽略 + 跳过 [DONE]/空块。
it('parseSse 解析多事件缓冲', () => {
  const buf =
    'data: {"type":"response.output_text.delta","delta":"Red\\nGreen\\n"}\n\n' +
    'data: {"type":"response.output_text.delta","delta":"Blue"}\n\n' +
    'data: {"type":"response.completed"}\n\n'
  const evs = parseSse(buf)
  expect(evs).toHaveLength(3)
  expect(evs[0]).toEqual({ type: 'response.output_text.delta', delta: 'Red\nGreen\n' })
  expect(evs[1].delta).toBe('Blue')
  expect(evs[2].type).toBe('response.completed')
})

it('parseSse 忽略半包(不完整 JSON)与 [DONE]/空块', () => {
  const buf =
    'data: {"type":"response.output_text.delta","delta":"ok"}\n\n' +
    'data: {"type":"response.output_text.de\n\n' +   // 半包
    'data: [DONE]\n\n' +
    '\n\n'
  const evs = parseSse(buf)
  expect(evs).toHaveLength(1)
  expect(evs[0].delta).toBe('ok')
})

// applyStreamEvent:output_text.delta 追加到末尾 assistant 气泡 / 否则起新气泡。
it('applyStreamEvent:delta 起新 assistant 气泡(末尾非 assistant)', () => {
  const start: ChatItem[] = [{ kind: 'user', text: 'hi' }]
  const next = applyStreamEvent(start, { type: 'response.output_text.delta', delta: 'Red\n' })
  expect(next).toEqual([{ kind: 'user', text: 'hi' }, { kind: 'assistant', text: 'Red\n' }])
})

it('applyStreamEvent:delta 追加到末尾 assistant 气泡', () => {
  const start: ChatItem[] = [{ kind: 'assistant', text: 'Red\n' }]
  const next = applyStreamEvent(start, { type: 'response.output_text.delta', delta: 'Green' })
  expect(next).toEqual([{ kind: 'assistant', text: 'Red\nGreen' }])
})

it('applyStreamEvent:非 delta 事件原样返回(不在 completed 处改动)', () => {
  const start: ChatItem[] = [{ kind: 'assistant', text: 'x' }]
  expect(applyStreamEvent(start, { type: 'response.completed' })).toBe(start)
  expect(applyStreamEvent(start, { type: 'session.created' })).toBe(start)
})

// dedupeChat:折叠连续相同 kind+text 的气泡(乐观 user 与 refetch 重叠)。
it('dedupeChat 折叠连续相同气泡', () => {
  const items: ChatItem[] = [
    { kind: 'user', text: 'hi' },
    { kind: 'user', text: 'hi' },       // 乐观 + refetch 重叠
    { kind: 'assistant', text: 'yo' },
    { kind: 'assistant', text: 'yo' },
    { kind: 'assistant', text: 'yo2' }, // 不同 text → 保留
  ]
  expect(dedupeChat(items)).toEqual([
    { kind: 'user', text: 'hi' },
    { kind: 'assistant', text: 'yo' },
    { kind: 'assistant', text: 'yo2' },
  ])
})
