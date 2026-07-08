import { it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { Shell } from './Shell'
it('二级面板可折叠(含子页的一级项)', () => {
  // 智能体一级项有子页 → 二级面板显示;折叠隐藏、展开恢复(图标栏常驻)。
  render(<MemoryRouter initialEntries={['/agents']}><Shell /></MemoryRouter>)
  expect(screen.queryByTestId('secondary-nav')).toBeTruthy()
  fireEvent.click(screen.getByLabelText('折叠面板'))
  expect(screen.queryByTestId('secondary-nav')).toBeNull()
  fireEvent.click(screen.getByLabelText('展开面板'))
  expect(screen.queryByTestId('secondary-nav')).toBeTruthy()
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
