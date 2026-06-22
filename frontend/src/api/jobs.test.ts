import { it, expect, vi } from 'vitest'
import { pollJob } from './jobs'

// pollJob 必须按 `terminal` 字段判终态(FR-007),不是状态串匹配。
it('按 terminal 轮询到终态(非状态串匹配)', async () => {
  const seq = [
    { terminal: false, status: 'running' },
    { terminal: false, status: 'running' },
    { terminal: true, status: 'succeeded' },
  ]
  let i = 0
  vi.spyOn(globalThis, 'fetch').mockImplementation(
    async () => new Response(JSON.stringify(seq[i++]), { status: 200 }),
  )
  const final = await pollJob('job-1', { intervalMs: 1 })
  expect(final.terminal).toBe(true)
  expect(final.status).toBe('succeeded')
})
