import { it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { Shell } from './Shell'
it('侧栏可折叠', () => {
  render(<MemoryRouter><Shell /></MemoryRouter>)
  const aside = document.querySelector('aside')!
  expect(aside.className).toContain('w-64')
  fireEvent.click(screen.getByLabelText('折叠侧栏'))
  expect(aside.className).toContain('w-16')
})

it('无企业账号在数据页显示「待分配」引导,而非 403(FR-003)', async () => {
  // /v1/me/orgs 返回空 memberships(注册了但未被企业授予)→ 数据路由显友好引导
  vi.stubGlobal('fetch', vi.fn(async (url: any) =>
    String(url).includes('/v1/me/orgs')
      ? { ok: true, status: 200, json: async () => ({ user: 'u', is_platform_admin: false, memberships: [], enterprises: [] }) }
      : { ok: true, status: 200, json: async () => ({}) },
  ))
  render(<MemoryRouter initialEntries={['/datasets']}><Shell /></MemoryRouter>)
  await waitFor(() => expect(screen.getByText('你还未加入任何企业')).toBeTruthy())
})

const realLocation = window.location
function mockAssign() {
  // jsdom 的 location.assign 不可单独 redefine,整体替换 window.location(configurable)
  const assign = vi.fn()
  Object.defineProperty(window, 'location', { configurable: true, value: { ...realLocation, assign } })
  return assign
}
afterEach(() => {
  Object.defineProperty(window, 'location', { configurable: true, value: realLocation })
  vi.unstubAllGlobals()
})

it('登出整页跳转到 BFF 返回的 KC end_session(无缝登出)', async () => {
  const assign = mockAssign()
  vi.stubGlobal('fetch', vi.fn(async () => ({
    ok: true, status: 200, json: async () => ({ ok: true, end_session: 'http://kc/logout?id_token_hint=x' }),
  })))
  render(<MemoryRouter><Shell /></MemoryRouter>)
  fireEvent.click(screen.getByText('登出'))
  await waitFor(() => expect(assign).toHaveBeenCalledWith('http://kc/logout?id_token_hint=x'))
})

it('登出降级:拿不到 end_session 仍回 /auth/login', async () => {
  const assign = mockAssign()
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ ok: true }) })))
  render(<MemoryRouter><Shell /></MemoryRouter>)
  fireEvent.click(screen.getByText('登出'))
  await waitFor(() => expect(assign).toHaveBeenCalledWith('/auth/login'))
})
