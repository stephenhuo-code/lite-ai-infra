import { it, expect } from 'vitest'
import { mapItems } from './omnigent'

// mapItems:omnigent 会话条目 → ChatItem[](role→kind,拼接 text/output_text content)。
it('映射 user/assistant role,拼接 text + output_text content', () => {
  const raw = [
    { id: 'i1', role: 'user', content: [{ type: 'text', text: '你好' }] },
    { id: 'i2', role: 'assistant', content: [
      { type: 'output_text', text: 'Red\n' },
      { type: 'output_text', text: 'Green' },
    ] },
  ]
  expect(mapItems(raw)).toEqual([
    { kind: 'user', text: '你好' },
    { kind: 'assistant', text: 'Red\nGreen' },
  ])
})

it('丢弃非 user/assistant role(tool/system 等),9a = 纯文本对话', () => {
  const raw = [
    { id: 'i1', role: 'system', content: [{ type: 'text', text: 'sys' }] },
    { id: 'i2', role: 'tool', content: [{ type: 'text', text: 'tool out' }] },
    { id: 'i3', role: 'assistant', content: [{ type: 'text', text: 'ok' }] },
  ]
  expect(mapItems(raw)).toEqual([{ kind: 'assistant', text: 'ok' }])
})

it('忽略非 text 类型的 content,缺 content 视作空文本', () => {
  const raw = [
    { id: 'i1', role: 'assistant', content: [
      { type: 'reasoning', text: '思考' },
      { type: 'text', text: '答案' },
    ] },
    { id: 'i2', role: 'user' },   // 无 content
  ]
  expect(mapItems(raw)).toEqual([
    { kind: 'assistant', text: '答案' },
    { kind: 'user', text: '' },
  ])
})
