import { it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { CreateAgentModal } from './CreateAgentModal'

// 新建/编辑弹窗:harness 下拉 + 条件 API Key 字段 + 客户端校验镜像服务端门 +
// 双模(create/edit,edit 破坏性覆盖告警 + 预填 name/harness + 走 PUT)。
// POST/PUT 经 fetch mock 验证。

let lastBody: any = null
let lastUrl = ''
let lastMethod = ''

beforeEach(() => {
  lastBody = null; lastUrl = ''; lastMethod = ''
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url: any, init?: any) => {
    lastUrl = String(url); lastMethod = init?.method
    if (init?.body) lastBody = JSON.parse(init.body)
    return new Response(JSON.stringify({ id: 'ag_x', name: lastBody?.name ?? '' }), { status: 200 })
  })
})
afterEach(() => { vi.restoreAllMocks() })

it('默认 claude-native:隐藏 API Key 字段', () => {
  render(<CreateAgentModal onClose={() => {}} onDone={() => {}} />)
  expect(screen.queryByLabelText('API Key *')).toBeNull()
})

it('选 SDK harness 显示 API Key 字段(password 型)', () => {
  render(<CreateAgentModal onClose={() => {}} onDone={() => {}} />)
  fireEvent.change(screen.getByLabelText('基底 harness'), { target: { value: 'claude-sdk' } })
  const key = screen.getByLabelText('API Key *') as HTMLInputElement
  expect(key).toBeTruthy()
  expect(key.type).toBe('password') // 红线:password 型
})

it('SDK harness 缺 key:阻止提交(不调 createAgent)+ 提示', async () => {
  render(<CreateAgentModal onClose={() => {}} onDone={() => {}} />)
  fireEvent.change(screen.getByLabelText('名字 *'), { target: { value: 'sdk助手' } })
  fireEvent.change(screen.getByLabelText('基底 harness'), { target: { value: 'claude-sdk' } })
  fireEvent.click(screen.getByText('创建'))
  await waitFor(() => expect(screen.getByText(/请填写/)).toBeTruthy())
  expect(lastBody).toBeNull() // 未发起请求
})

it('claude-sdk + key:调 createAgent 带 {harness:claude-sdk, api_key}', async () => {
  const onDone = vi.fn()
  render(<CreateAgentModal onClose={() => {}} onDone={onDone} />)
  fireEvent.change(screen.getByLabelText('名字 *'), { target: { value: 'sdk助手' } })
  fireEvent.change(screen.getByLabelText('基底 harness'), { target: { value: 'claude-sdk' } })
  fireEvent.change(screen.getByLabelText('API Key *'), { target: { value: 'sk-real-key' } })
  fireEvent.click(screen.getByText('创建'))
  await waitFor(() => expect(onDone).toHaveBeenCalled())
  expect(lastMethod).toBe('POST')
  expect(lastBody.harness).toBe('claude-sdk')
  expect(lastBody.api_key).toBe('sk-real-key')
})

it('${SECRET} 形式 key:客户端拦截 + 友好提示(不发请求)', async () => {
  render(<CreateAgentModal onClose={() => {}} onDone={() => {}} />)
  fireEvent.change(screen.getByLabelText('名字 *'), { target: { value: 'sdk助手' } })
  fireEvent.change(screen.getByLabelText('基底 harness'), { target: { value: 'claude-sdk' } })
  fireEvent.change(screen.getByLabelText('API Key *'), { target: { value: '${SECRET}' } })
  fireEvent.click(screen.getByText('创建'))
  await waitFor(() => expect(screen.getByText(/变量引用/)).toBeTruthy())
  expect(lastBody).toBeNull()
})

it('claude-native:不下发 api_key(切回隐藏后)', async () => {
  const onDone = vi.fn()
  render(<CreateAgentModal onClose={() => {}} onDone={onDone} />)
  fireEvent.change(screen.getByLabelText('名字 *'), { target: { value: '原生助手' } })
  // 默认 claude-native
  fireEvent.click(screen.getByText('创建'))
  await waitFor(() => expect(onDone).toHaveBeenCalled())
  expect(lastBody.harness).toBe('claude-native')
  expect('api_key' in lastBody).toBe(false)
})

it('编辑模式:标题「编辑智能体」+ 预填 name/harness + 破坏性覆盖告警', () => {
  render(
    <CreateAgentModal
      mode="edit"
      agent={{ id: 'ag1', name: '客服助手', harness: 'codex', enterprise_owned: true }}
      onClose={() => {}}
      onDone={() => {}}
    />,
  )
  expect(screen.getByText('编辑智能体')).toBeTruthy()
  expect((screen.getByLabelText('名字 *') as HTMLInputElement).value).toBe('客服助手')
  expect((screen.getByLabelText('基底 harness') as HTMLSelectElement).value).toBe('codex')
  expect(screen.getByText(/整体覆盖/)).toBeTruthy()
  expect(screen.getByText(/将被清除/)).toBeTruthy()
})

it('编辑模式:提交走 PUT /v1/ws/agents/{id}', async () => {
  const onDone = vi.fn()
  render(
    <CreateAgentModal
      mode="edit"
      agent={{ id: 'ag1', name: '客服助手', harness: 'claude-native', enterprise_owned: true }}
      onClose={() => {}}
      onDone={onDone}
    />,
  )
  fireEvent.change(screen.getByLabelText('名字 *'), { target: { value: '客服助手V2' } })
  fireEvent.click(screen.getByText('保存'))
  await waitFor(() => expect(onDone).toHaveBeenCalled())
  expect(lastMethod).toBe('PUT')
  expect(lastUrl).toBe('/v1/ws/agents/ag1')
  expect(lastBody.name).toBe('客服助手V2')
})
