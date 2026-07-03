import { it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'
import { Agents } from './Agents'

// 智能体库页(ADR-027):列出本企业可见智能体(内置 + 本企业)+ 徽标;
// 企业管理员见「新建智能体」入口,普通成员不见(角色由 GET /v1/me/orgs 决定);
// 提交创建 → POST /v1/ws/agents body 正确 → 刷新列表。
// 角色 / 列表 / 创建均经 fetch mock(useOrgs 与 api 都用 fetch)。

let lastCreateBody: any = null
let lastDeleteId: string | null = null

beforeEach(() => { lastDeleteId = null; vi.restoreAllMocks() })
afterEach(() => { vi.restoreAllMocks() })

const BUILTIN = { id: 'ag_builtin', name: 'claude-native-ui', harness: 'claude-native', description: '内置通用助手', builtin: true, enterprise_owned: false }
const OWNED = { id: 'ag_owned', name: '客服助手', harness: 'claude-native', description: '只答产品问题', builtin: false, enterprise_owned: true }

// role: 'enterprise-admin' | 'member' —— 控制 /v1/me/orgs 返回的角色。
// createdAgents: 初次列表;创建成功后会被追加(模拟刷新)。
function mockApis(role: string) {
  lastCreateBody = null
  const created: any[] = []
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url: any, init?: any) => {
    const u = String(url)
    if (u === '/v1/me/orgs') {
      return new Response(JSON.stringify({
        user: 'alice', is_platform_admin: false,
        memberships: [{ enterprise_id: 'e-1', role }],
        enterprises: [{ alias: 'e-1', display_name: '企业一' }],
      }), { status: 200 })
    }
    if (u === '/v1/ws/agents' && init?.method === 'POST') {
      lastCreateBody = JSON.parse(init.body)
      const obj = { id: 'ag_new', name: lastCreateBody.name, harness: 'claude-native', description: '', builtin: false, enterprise_owned: true }
      created.push(obj)
      return new Response(JSON.stringify(obj), { status: 200 })
    }
    if (u.startsWith('/v1/ws/agents/') && init?.method === 'DELETE') {
      lastDeleteId = decodeURIComponent(u.split('/').pop() || '')
      return new Response(JSON.stringify({ deleted: true, id: lastDeleteId }), { status: 200 })
    }
    if (u === '/v1/ws/agents') {
      return new Response(JSON.stringify({ data: [BUILTIN, OWNED, ...created] }), { status: 200 })
    }
    return new Response('', { status: 404 })
  })
}

it('列出智能体并标 内置/本企业 徽标', async () => {
  mockApis('member')
  render(<Agents />)

  await waitFor(() => expect(screen.getByText('claude-native-ui')).toBeTruthy())
  expect(screen.getByText('客服助手')).toBeTruthy()

  // 卡片化后:徽标与名称同处一张卡(标题的最近 .rounded-2xl 卡容器)。
  const builtinCard = screen.getByText('claude-native-ui').closest('.rounded-2xl') as HTMLElement
  expect(within(builtinCard).getByText('内置')).toBeTruthy()
  const ownedCard = screen.getByText('客服助手').closest('.rounded-2xl') as HTMLElement
  expect(within(ownedCard).getByText('本企业')).toBeTruthy()
})

it('企业管理员见「新建智能体」入口', async () => {
  mockApis('enterprise-admin')
  render(<Agents />)
  await waitFor(() => expect(screen.getByText('claude-native-ui')).toBeTruthy())
  await waitFor(() => expect(screen.getByText('新建智能体')).toBeTruthy())
})

it('普通成员【不见】「新建智能体」入口', async () => {
  mockApis('member')
  render(<Agents />)
  await waitFor(() => expect(screen.getByText('claude-native-ui')).toBeTruthy())
  // 角色加载完成后仍无入口
  await new Promise(r => setTimeout(r, 0))
  expect(screen.queryByText('新建智能体')).toBeNull()
})

it('管理员提交创建 → POST body 正确(harness=claude-native)且刷新列表', async () => {
  mockApis('enterprise-admin')
  render(<Agents />)
  await waitFor(() => expect(screen.getByText('新建智能体')).toBeTruthy())

  // 打开弹窗
  fireEvent.click(screen.getByText('新建智能体'))
  await screen.findByLabelText('基底 harness')

  // 填名字 + 提示词 + 模型
  fireEvent.change(screen.getByLabelText('名字 *'), { target: { value: '销售助手' } })
  fireEvent.change(screen.getByLabelText('系统提示词(可选)'), { target: { value: '你是销售助手' } })
  fireEvent.change(screen.getByLabelText('模型(可选)'), { target: { value: 'claude-sonnet' } })

  fireEvent.click(screen.getByText('创建'))

  await waitFor(() => expect(lastCreateBody).not.toBeNull())
  expect(lastCreateBody.name).toBe('销售助手')
  expect(lastCreateBody.instructions).toBe('你是销售助手')
  expect(lastCreateBody.model).toBe('claude-sonnet')
  expect(lastCreateBody.harness).toBe('claude-native') // 红线:仅 claude-native
  // 9b 范围字段不得出现(无 MCP/工具/数据/凭据)
  expect('mcp' in lastCreateBody).toBe(false)
  expect('credentials' in lastCreateBody).toBe(false)

  // 刷新后新智能体出现在列表
  await waitFor(() => expect(screen.getByText('销售助手')).toBeTruthy())
})

it('「编辑」按钮仅在本企业卡片出现(内置卡片无),且管理员可见', async () => {
  mockApis('enterprise-admin')
  render(<Agents />)
  await waitFor(() => expect(screen.getByText('客服助手')).toBeTruthy())

  const ownedCard = screen.getByText('客服助手').closest('.rounded-2xl') as HTMLElement
  expect(within(ownedCard).getByText('编辑')).toBeTruthy()

  const builtinCard = screen.getByText('claude-native-ui').closest('.rounded-2xl') as HTMLElement
  expect(within(builtinCard).queryByText('编辑')).toBeNull() // 内置不可编辑
})

it('普通成员【不见】「编辑」按钮(仅 UX 门)', async () => {
  mockApis('member')
  render(<Agents />)
  await waitFor(() => expect(screen.getByText('客服助手')).toBeTruthy())
  await new Promise(r => setTimeout(r, 0))
  expect(screen.queryByText('编辑')).toBeNull()
})

it('「删除」仅在本企业卡片(内置无);确认后走 DELETE + 刷新', async () => {
  const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
  mockApis('enterprise-admin')
  render(<Agents />)
  await waitFor(() => expect(screen.getByText('客服助手')).toBeTruthy())

  // 内置卡片无「删除」(全局共享,不可删)
  const builtinCard = screen.getByText('claude-native-ui').closest('.rounded-2xl') as HTMLElement
  expect(within(builtinCard).queryByText('删除')).toBeNull()

  // 本企业卡片有「删除」→ 点击 → 确认 → DELETE 本 agent id
  const ownedCard = screen.getByText('客服助手').closest('.rounded-2xl') as HTMLElement
  fireEvent.click(within(ownedCard).getByText('删除'))
  await waitFor(() => expect(lastDeleteId).toBe('ag_owned'))
  confirmSpy.mockRestore()
})

it('删除二次确认取消 → 不发 DELETE', async () => {
  const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)
  mockApis('enterprise-admin')
  render(<Agents />)
  await waitFor(() => expect(screen.getByText('客服助手')).toBeTruthy())
  const ownedCard = screen.getByText('客服助手').closest('.rounded-2xl') as HTMLElement
  fireEvent.click(within(ownedCard).getByText('删除'))
  await new Promise(r => setTimeout(r, 0))
  expect(lastDeleteId).toBeNull()
  confirmSpy.mockRestore()
})

it('内置卡片「复制为本企业」→ create 弹窗预填名字副本 + 同基底', async () => {
  mockApis('enterprise-admin')
  render(<Agents />)
  await waitFor(() => expect(screen.getByText('claude-native-ui')).toBeTruthy())

  const builtinCard = screen.getByText('claude-native-ui').closest('.rounded-2xl') as HTMLElement
  fireEvent.click(within(builtinCard).getByText('复制为本企业'))

  // create 弹窗(非编辑):预填"<内置名> 副本",无覆盖告警
  await waitFor(() =>
    expect((screen.getByLabelText('名字 *') as HTMLInputElement).value).toBe('claude-native-ui 副本'))
  expect(screen.queryByText(/整体覆盖/)).toBeNull()   // create 模式无编辑覆盖告警
})

it('点「编辑」→ 编辑弹窗(预填 name/harness + 覆盖告警),提交走 PUT 后刷新', async () => {
  let putBody: any = null
  let putUrl = ''
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url: any, init?: any) => {
    const u = String(url)
    if (u === '/v1/me/orgs') {
      return new Response(JSON.stringify({
        user: 'alice', is_platform_admin: false,
        memberships: [{ enterprise_id: 'e-1', role: 'enterprise-admin' }],
        enterprises: [{ alias: 'e-1', display_name: '企业一' }],
      }), { status: 200 })
    }
    if (init?.method === 'PUT') {
      putUrl = u; putBody = JSON.parse(init.body)
      return new Response(JSON.stringify({ id: 'ag_owned', name: putBody.name, has_api_key: false }), { status: 200 })
    }
    if (u === '/v1/ws/agents') {
      const renamed = { ...OWNED, name: putBody?.name ?? OWNED.name }
      return new Response(JSON.stringify({ data: [BUILTIN, putBody ? renamed : OWNED] }), { status: 200 })
    }
    return new Response('', { status: 404 })
  })
  render(<Agents />)
  await waitFor(() => expect(screen.getByText('客服助手')).toBeTruthy())

  const ownedCard = screen.getByText('客服助手').closest('.rounded-2xl') as HTMLElement
  fireEvent.click(within(ownedCard).getByText('编辑'))

  // 编辑弹窗:标题 + 预填 + 覆盖告警
  await screen.findByText('编辑智能体')
  expect((screen.getByLabelText('名字 *') as HTMLInputElement).value).toBe('客服助手')
  expect(screen.getByText(/整体覆盖/)).toBeTruthy()

  fireEvent.change(screen.getByLabelText('名字 *'), { target: { value: '客服助手V2' } })
  fireEvent.click(screen.getByText('保存'))

  await waitFor(() => expect(putUrl).toBe('/v1/ws/agents/ag_owned'))
  expect(putBody.name).toBe('客服助手V2')
  await waitFor(() => expect(screen.getByText('客服助手V2')).toBeTruthy())
})

it('非管理员后端 403 兜底:创建接口被拒时弹窗显可理解提示', async () => {
  // 即便绕过 UI(此处直接验证 modal 的 403 文案路径),前端不靠藏按钮兜底。
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url: any, init?: any) => {
    const u = String(url)
    if (u === '/v1/me/orgs') {
      return new Response(JSON.stringify({
        user: 'alice', is_platform_admin: false,
        memberships: [{ enterprise_id: 'e-1', role: 'enterprise-admin' }],
        enterprises: [],
      }), { status: 200 })
    }
    if (u === '/v1/ws/agents' && init?.method === 'POST') {
      return new Response(JSON.stringify({ reason: 'forbidden' }), { status: 403 })
    }
    if (u === '/v1/ws/agents') return new Response(JSON.stringify({ data: [BUILTIN] }), { status: 200 })
    return new Response('', { status: 404 })
  })
  render(<Agents />)
  await waitFor(() => expect(screen.getByText('新建智能体')).toBeTruthy())
  fireEvent.click(screen.getByText('新建智能体'))
  fireEvent.change(await screen.findByLabelText('名字 *'), { target: { value: 'x' } })
  fireEvent.click(screen.getByText('创建'))
  await waitFor(() => expect(screen.getByText(/没有创建智能体的权限/)).toBeTruthy())
})
