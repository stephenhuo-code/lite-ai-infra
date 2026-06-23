import { it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { Shell } from './Shell'
it('侧栏可折叠', () => {
  render(<MemoryRouter><Shell /></MemoryRouter>)
  const aside = document.querySelector('aside')!
  expect(aside.className).toContain('w-64')
  fireEvent.click(screen.getByLabelText('折叠'))
  expect(aside.className).toContain('w-16')
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
