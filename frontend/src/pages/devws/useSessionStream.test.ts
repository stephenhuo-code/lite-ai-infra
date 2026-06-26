import { it, expect } from 'vitest'
import { applyStreamEvent, type ChatItem } from './useSessionStream'

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
