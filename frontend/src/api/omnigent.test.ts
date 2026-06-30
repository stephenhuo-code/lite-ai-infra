import { it, expect, vi, afterEach } from 'vitest'
import { mapItems, listLibraryAgents, createAgent, updateAgent } from './omnigent'

afterEach(() => { vi.restoreAllMocks() })

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

it('实测形状:user 用 input_text、assistant 用 output_text,非 message 条目(resource_event)丢弃', () => {
  // 取自真实 omnigent /items 响应:user content 是 `input_text`(非 `text`),
  // assistant 是 `output_text`,且历史里夹带无 role 的 resource_event 条目。
  const raw = [
    { id: 'rse_1', type: 'resource_event', event_type: 'session.resource.created', resource_type: 'terminal' },
    { id: 'm1', type: 'message', role: 'user', content: [{ type: 'input_text', text: 'Reply with: HELLO_9A' }] },
    { id: 'm2', type: 'message', role: 'assistant', content: [{ type: 'output_text', text: 'HELLO_9A' }] },
  ]
  expect(mapItems(raw)).toEqual([
    { kind: 'user', text: 'Reply with: HELLO_9A' },   // 回归守卫:input_text 不得被丢
    { kind: 'assistant', text: 'HELLO_9A' },
  ])
})

// listLibraryAgents:GET /v1/ws/agents → 解 { data: [...] }(含 builtin/enterprise_owned 标志)。
it('listLibraryAgents 解出 data 数组及标志', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
    data: [{ id: 'ag1', name: '客服', harness: 'claude-native', builtin: false, enterprise_owned: true }],
  }), { status: 200 }))
  const ags = await listLibraryAgents()
  expect(ags).toEqual([{ id: 'ag1', name: '客服', harness: 'claude-native', builtin: false, enterprise_owned: true }])
})

// createAgent:POST /v1/ws/agents,body 去空白、harness 默认 claude-native、空可选项不发。
it('createAgent POST body:trim + harness 默认 claude-native + 省略空可选项', async () => {
  let body: any = null
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (_u: any, init?: any) => {
    body = JSON.parse(init.body)
    return new Response(JSON.stringify({ id: 'ag_new', name: body.name }), { status: 200 })
  })
  await createAgent({ name: '  客服助手  ', instructions: '  你是客服  ', model: '' })
  expect(body.name).toBe('客服助手')
  expect(body.instructions).toBe('你是客服')
  expect(body.harness).toBe('claude-native')  // 红线:仅 claude-native
  expect('model' in body).toBe(false)         // 空 model 不发
  expect('description' in body).toBe(false)
})

// createAgent:SDK harness 透传 harness + api_key + base_url(去空白)。
it('createAgent 透传 harness/api_key/base_url(SDK harness)', async () => {
  let body: any = null
  let calledUrl = ''
  let calledMethod = ''
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (u: any, init?: any) => {
    calledUrl = String(u); calledMethod = init?.method
    body = JSON.parse(init.body)
    return new Response(JSON.stringify({ id: 'ag_new', name: body.name }), { status: 200 })
  })
  await createAgent({ name: 'sdk助手', harness: 'claude-sdk', api_key: '  sk-abc  ', base_url: ' https://x.test ' })
  expect(calledUrl).toBe('/v1/ws/agents')
  expect(calledMethod).toBe('POST')
  expect(body.harness).toBe('claude-sdk')
  expect(body.api_key).toBe('sk-abc')
  expect(body.base_url).toBe('https://x.test')
})

// updateAgent:PUT /v1/ws/agents/{id},body 与 create 同形(trim + 默认 harness)。
it('updateAgent PUT 到 /v1/ws/agents/{id} 且 body 同形', async () => {
  let body: any = null
  let calledUrl = ''
  let calledMethod = ''
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (u: any, init?: any) => {
    calledUrl = String(u); calledMethod = init?.method
    body = JSON.parse(init.body)
    return new Response(JSON.stringify({ id: 'ag1', name: body.name, has_api_key: true }), { status: 200 })
  })
  await updateAgent('ag 1', { name: ' 改名 ', harness: 'codex', api_key: 'sk-z' })
  expect(calledUrl).toBe('/v1/ws/agents/ag%201') // id 经 encodeURIComponent
  expect(calledMethod).toBe('PUT')
  expect(body.name).toBe('改名')
  expect(body.harness).toBe('codex')
  expect(body.api_key).toBe('sk-z')
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
