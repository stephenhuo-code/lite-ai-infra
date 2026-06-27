import { it, expect } from 'vitest'
import { applyStreamEvent, dedupeChat, type ChatItem } from './useSessionStream'

it('dedupeChat collapses consecutive identical user/assistant bubbles', () => {
  const s = dedupeChat([
    { kind: 'user', text: '探查 coco-2' },
    { kind: 'user', text: '探查 coco-2' },        // claude-native 回灌的重复 → 折叠
    { kind: 'assistant', text: 'coco-2 有 2 列' },
  ])
  expect(s).toEqual([
    { kind: 'user', text: '探查 coco-2' },
    { kind: 'assistant', text: 'coco-2 有 2 列' },
  ])
})

it('output_text.delta accumulates into one assistant bubble', () => {
  let s: ChatItem[] = []
  s = applyStreamEvent(s, { type: 'response.output_text.delta', delta: '你好' })
  s = applyStreamEvent(s, { type: 'response.output_text.delta', delta:'，世界' })
  expect(s).toEqual([{ kind: 'assistant', text: '你好,世界'.replace(',', '，') }])
})

it('output_item.done(function_call) adds a tool card', () => {
  const s = applyStreamEvent([], {
    type: 'response.output_item.done',
    item: { type: 'function_call', name: 'liteai__catalog_read_schema' },
  })
  expect(s).toEqual([{ kind: 'tool', name: 'liteai__catalog_read_schema' }])
})

it('elicitation request adds an ASK card', () => {
  const s = applyStreamEvent([], {
    type: 'response.elicitation.requested',
    elicitation_id: 'el-1', message: 'run_dj?',
  })
  expect(s).toEqual([{ kind: 'ask', id: 'el-1', prompt: 'run_dj?' }])
})

it('ignores unknown / lifecycle events', () => {
  expect(applyStreamEvent([], { type: 'response.created' })).toEqual([])
  expect(applyStreamEvent([], { type: 'heartbeat' })).toEqual([])
})
