import { it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'
import { Workspace } from './Workspace'

// Workspace 智能体选择(ADR-027):新建会话前先弹智能体选择器,确认后 POST /v1/ws/sessions
// 携所选 agent_id;会话锁定到该智能体——界面无"换智能体"入口(锁定不变式)。

let lastSessionBody: any = null

beforeEach(() => { vi.restoreAllMocks() })
afterEach(() => { vi.restoreAllMocks() })

const AGENTS = [
  { id: 'ag_builtin', name: 'claude-native-ui', harness: 'claude-native', builtin: true, enterprise_owned: false },
  { id: 'ag_cs', name: '客服助手', harness: 'claude-native', builtin: false, enterprise_owned: true },
]

function mockApis() {
  lastSessionBody = null
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url: any, init?: any) => {
    const u = String(url)
    if (u === '/v1/ws/agents') return new Response(JSON.stringify({ data: AGENTS }), { status: 200 })
    if (u === '/v1/ws/sessions' && init?.method === 'POST') {
      lastSessionBody = JSON.parse(init.body)
      return new Response(JSON.stringify({ id: 'sess_1' }), { status: 200 })
    }
    if (u === '/v1/ws/sessions') return new Response(JSON.stringify({ data: [] }), { status: 200 })
    if (u.includes('/items')) return new Response(JSON.stringify({ data: [] }), { status: 200 })
    if (u.includes('/stream')) return new Response('', { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
    return new Response('', { status: 404 })
  })
}

it('新建会话前弹智能体选择器,选定后 createSession 带所选 agent_id', async () => {
  mockApis()
  render(<Workspace />)

  // 库加载完成(默认预选)后点「新会话」→ 弹选择器
  await waitFor(() => expect(screen.getByText('+ 新会话')).toBeTruthy())
  fireEvent.click(screen.getByText('+ 新会话'))

  const select = await screen.findByLabelText('选择智能体')
  // 选「客服助手」
  fireEvent.change(select, { target: { value: 'ag_cs' } })
  fireEvent.click(screen.getByText('开始对话'))

  await waitFor(() => expect(lastSessionBody).not.toBeNull())
  expect(lastSessionBody.agent_id).toBe('ag_cs')

  // 会话建好后展示所选智能体名 + 已锁定;无"换智能体"入口
  await waitFor(() => expect(screen.getByText('已锁定')).toBeTruthy())
  const header = screen.getByText('已锁定').closest('div')!
  expect(within(header).getByText('客服助手')).toBeTruthy()
})

it('对话进行中无"换智能体"控件(锁定不变式)', async () => {
  mockApis()
  render(<Workspace />)
  await waitFor(() => expect(screen.getByText('+ 新会话')).toBeTruthy())
  fireEvent.click(screen.getByText('+ 新会话'))
  fireEvent.click(await screen.findByText('开始对话'))   // 用默认预选(claude-native-ui)建

  await waitFor(() => expect(lastSessionBody).not.toBeNull())
  expect(lastSessionBody.agent_id).toBe('ag_builtin')   // 默认预选内置

  // 会话锁定后:无任何"换/切换智能体"入口
  await waitFor(() => expect(screen.getByText('已锁定')).toBeTruthy())
  expect(screen.queryByText(/换智能体|切换智能体|更换智能体/)).toBeNull()
  // 选择器只在新建会话时出现,会话进行中不残留
  expect(screen.queryByLabelText('选择智能体')).toBeNull()
})

it('默认预选 claude-native-ui 内置模板', async () => {
  mockApis()
  render(<Workspace />)
  await waitFor(() => expect(screen.getByText('+ 新会话')).toBeTruthy())
  fireEvent.click(screen.getByText('+ 新会话'))

  const select = await screen.findByLabelText('选择智能体') as HTMLSelectElement
  expect(select.value).toBe('ag_builtin') // claude-native-ui
})

it('建会话失败 → 明确反馈,不静默卡死(spec Edge Case)', async () => {
  // POST /v1/ws/sessions 返回 403(如跨企业/无权)→ createSession 抛 → 选择器显错、可重试。
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url: any, init?: any) => {
    const u = String(url)
    if (u === '/v1/ws/agents') return new Response(JSON.stringify({ data: AGENTS }), { status: 200 })
    if (u === '/v1/ws/sessions' && init?.method === 'POST') return new Response('', { status: 403 })
    if (u === '/v1/ws/sessions') return new Response(JSON.stringify({ data: [] }), { status: 200 })
    return new Response('', { status: 404 })
  })
  render(<Workspace />)

  await waitFor(() => expect(screen.getByText('+ 新会话')).toBeTruthy())
  fireEvent.click(screen.getByText('+ 新会话'))
  fireEvent.click(await screen.findByText('开始对话'))

  // 错误被明确呈现(alert),选择器仍开着、按钮回到可点(可重试),不残留半成品会话(无"已锁定")
  await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy())
  expect(screen.getByRole('alert').textContent).toMatch(/无权限|不属于本企业|建会话失败/)
  expect(screen.getByLabelText('选择智能体')).toBeTruthy()       // 选择器没关
  expect(screen.queryByText('已锁定')).toBeNull()                // 没残留会话
  expect((screen.getByText('开始对话') as HTMLButtonElement).disabled).toBe(false)
})
