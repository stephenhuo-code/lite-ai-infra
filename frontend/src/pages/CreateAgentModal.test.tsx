import { it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { CreateAgentModal } from './CreateAgentModal'

// 新建/编辑弹窗:名字(必填)+ harness 下拉 + 提示词/模型(可选)。
// 凭据不再随 agent 走(改由「模型配置」统一管),故【无 API Key 字段】。
// 双模(create/edit,edit 破坏性覆盖告警 + 预填 name/harness + 走 PUT)。POST/PUT 经 fetch mock 验证。

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

it('表单不含 API Key / Base URL 字段(凭据走「模型配置」)', () => {
  render(<CreateAgentModal onClose={() => {}} onDone={() => {}} />)
  expect(screen.queryByLabelText('API Key *')).toBeNull()
  expect(screen.queryByLabelText(/Base URL/)).toBeNull()
})

it('选任一 SDK harness 仍不出现 API Key 字段', () => {
  render(<CreateAgentModal onClose={() => {}} onDone={() => {}} />)
  fireEvent.change(screen.getByLabelText('基底 harness'), { target: { value: 'codex' } })
  expect(screen.queryByLabelText('API Key *')).toBeNull()
})

it('创建:调 createAgent(POST),body 无 api_key/base_url', async () => {
  const onDone = vi.fn()
  render(<CreateAgentModal onClose={() => {}} onDone={onDone} />)
  fireEvent.change(screen.getByLabelText('名字 *'), { target: { value: 'codex助手' } })
  fireEvent.change(screen.getByLabelText('基底 harness'), { target: { value: 'codex' } })
  fireEvent.click(screen.getByText('创建'))
  await waitFor(() => expect(onDone).toHaveBeenCalled())
  expect(lastMethod).toBe('POST')
  expect(lastBody.harness).toBe('codex')
  expect('api_key' in lastBody).toBe(false)
  expect('base_url' in lastBody).toBe(false)
})

it('名字为空:创建按钮禁用,点击不发请求', async () => {
  render(<CreateAgentModal onClose={() => {}} onDone={() => {}} />)
  const btn = screen.getByText('创建') as HTMLButtonElement
  expect(btn.disabled).toBe(true)
  fireEvent.click(btn)
  await new Promise(r => setTimeout(r, 0))
  expect(lastBody).toBeNull()
})

it('claude-native:提交 body 无 api_key', async () => {
  const onDone = vi.fn()
  render(<CreateAgentModal onClose={() => {}} onDone={onDone} />)
  fireEvent.change(screen.getByLabelText('名字 *'), { target: { value: '原生助手' } })
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
  expect('api_key' in lastBody).toBe(false)
})
