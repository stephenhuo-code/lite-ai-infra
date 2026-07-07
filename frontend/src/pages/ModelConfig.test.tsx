import { it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'
import { ModelConfig } from './ModelConfig'

// 模型配置页(每企业统一管模型凭据 · ADR-028):
// - 企业管理员见 provider 列表 + 可开配置表单;普通成员见「无权限」、无任何配置 UI;
// - 保存 provider 走 PUT /v1/ws/model-config/{provider} body {auth_type, value};
// - ${SECRET} 形式值客户端拦截(不发请求);
// - 红线:页面只显状态,【永不渲染密钥值】(GET 不回密钥)。
// 角色由 GET /v1/me/orgs 决定;model-config CRUD 经 fetch mock。

let lastPutUrl = ''
let lastPutBody: any = null

beforeEach(() => { lastPutUrl = ''; lastPutBody = null; vi.restoreAllMocks() })
afterEach(() => { vi.restoreAllMocks() })

// role: 'enterprise-admin' | 'member'。statuses: GET /v1/ws/model-config 的 providers。
function mockApis(role: string, statuses: any[] = []) {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url: any, init?: any) => {
    const u = String(url)
    if (u === '/v1/me/orgs') {
      return new Response(JSON.stringify({
        user: 'alice', is_platform_admin: false,
        memberships: [{ enterprise_id: 'e-1', role }],
        enterprises: [{ alias: 'e-1', display_name: '企业一' }],
      }), { status: 200 })
    }
    if (u === '/v1/ws/model-config' && (!init?.method || init.method === 'GET')) {
      return new Response(JSON.stringify({ providers: statuses }), { status: 200 })
    }
    if (u.startsWith('/v1/ws/model-config/') && init?.method === 'PUT') {
      lastPutUrl = u; lastPutBody = JSON.parse(init.body)
      return new Response(JSON.stringify({}), { status: 200 })
    }
    if (u.startsWith('/v1/ws/model-config/') && init?.method === 'DELETE') {
      return new Response(JSON.stringify({}), { status: 200 })
    }
    return new Response('', { status: 404 })
  })
}

it('企业管理员:见 provider 列表(Anthropic/OpenAI/MiniMax/DeepSeek,无 Gemini)', async () => {
  mockApis('enterprise-admin')
  render(<ModelConfig />)
  await waitFor(() => expect(screen.getByText('Anthropic (Claude)')).toBeTruthy())
  expect(screen.getByText('OpenAI (Codex)')).toBeTruthy()
  expect(screen.getByText('MiniMax')).toBeTruthy()
  expect(screen.getByText('DeepSeek')).toBeTruthy()
  expect(screen.queryByText('Gemini')).toBeNull()
})

it('普通成员:见「无权限」,无任何配置 UI', async () => {
  mockApis('member')
  render(<ModelConfig />)
  await waitFor(() => expect(screen.getByText(/仅企业管理员可访问/)).toBeTruthy())
  // 无 provider 行 / 无配置按钮
  expect(screen.queryByText('Anthropic (Claude)')).toBeNull()
  expect(screen.queryByText('配置')).toBeNull()
})

it('已配置的 provider:显 已配置徽标 + auth 类型,且【不渲染密钥值】', async () => {
  mockApis('enterprise-admin', [
    { provider: 'anthropic', configured: true, auth_type: 'api_key', has_base_url: false },
  ])
  render(<ModelConfig />)
  const card = (await waitFor(() => screen.getByText('Anthropic (Claude)'))).closest('.rounded-2xl') as HTMLElement
  expect(within(card).getByText('本企业已配置')).toBeTruthy()
  expect(within(card).getByText(/API key/)).toBeTruthy()
  // 密钥永不回显:掩码占位存在,页面无任何真实密钥文本
  expect(within(card).getByText(/••••••已配置/)).toBeTruthy()
  expect(document.body.textContent).not.toContain('sk-')
})

it('未配置的 provider:显「未配置」+「配置」,无「平台默认」', async () => {
  mockApis('enterprise-admin', [
    { provider: 'anthropic', configured: false, auth_type: null, has_base_url: false },
  ])
  render(<ModelConfig />)
  const card = (await waitFor(() => screen.getByText('Anthropic (Claude)'))).closest('.rounded-2xl') as HTMLElement
  expect(within(card).getByText('未配置')).toBeTruthy()
  expect(within(card).queryByText('平台默认')).toBeNull()
  expect(within(card).getByRole('button', { name: '配置' })).toBeTruthy()
  expect(within(card).queryByRole('button', { name: '覆盖' })).toBeNull()
  expect(within(card).queryByRole('button', { name: '清除' })).toBeNull()
})

it('保存 provider:调 PUT /v1/ws/model-config/{provider} body {auth_type, value}', async () => {
  mockApis('enterprise-admin')
  render(<ModelConfig />)
  const card = (await waitFor(() => screen.getByText('MiniMax'))).closest('.rounded-2xl') as HTMLElement
  fireEvent.click(within(card).getByText('配置'))

  await screen.findByLabelText('API key *')
  fireEvent.change(screen.getByLabelText('API key *'), { target: { value: 'real-mm-key' } })
  fireEvent.click(screen.getByText('保存'))

  await waitFor(() => expect(lastPutUrl).toBe('/v1/ws/model-config/minimax'))
  expect(lastPutBody.auth_type).toBe('api_key')
  expect(lastPutBody.value).toBe('real-mm-key')
})

it('${SECRET} 形式值:客户端拦截 + 友好提示(不发请求)', async () => {
  mockApis('enterprise-admin')
  render(<ModelConfig />)
  const card = (await waitFor(() => screen.getByText('MiniMax'))).closest('.rounded-2xl') as HTMLElement
  fireEvent.click(within(card).getByText('配置'))
  fireEvent.change(await screen.findByLabelText('API key *'), { target: { value: '${SECRET}' } })
  fireEvent.click(screen.getByText('保存'))
  await waitFor(() => expect(screen.getByText(/变量引用/)).toBeTruthy())
  expect(lastPutUrl).toBe('')
})

it('Anthropic:仅 API key(无凭据类型选择器,无订阅选项)', async () => {
  mockApis('enterprise-admin')
  render(<ModelConfig />)
  const card = (await waitFor(() => screen.getByText('Anthropic (Claude)'))).closest('.rounded-2xl') as HTMLElement
  fireEvent.click(within(card).getByText('配置'))
  await screen.findByLabelText('API key *')
  // 单一凭据类型 → 无选择器,固定显示「凭据类型:API key」
  expect(screen.queryByLabelText('凭据类型')).toBeNull()
  expect(screen.getByText('凭据类型:API key')).toBeTruthy()
  fireEvent.change(screen.getByLabelText('API key *'), { target: { value: 'sk-ant-real' } })
  fireEvent.click(screen.getByText('保存'))
  await waitFor(() => expect(lastPutBody?.auth_type).toBe('api_key'))
  expect(lastPutBody.value).toBe('sk-ant-real')
})
