import { it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { Account } from './Account'

// 身份降两级(ADR-025):账户页显示企业 **显示名**(FR-002b,非不透明 alias/UUID),
// 角色 member|enterprise-admin;enterprise-admin 见「邀请成员」入口 → POST /auth/orgs/invite。
beforeEach(() => { vi.restoreAllMocks() })
afterEach(() => { vi.restoreAllMocks() })

function mockApi(orgs: unknown, me: unknown, onInvite?: (body: unknown) => void) {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.includes('/v1/me/orgs')) return new Response(JSON.stringify(orgs), { status: 200 })
    if (url.includes('/auth/me')) return new Response(JSON.stringify(me), { status: 200 })
    if (url.includes('/auth/orgs/invite')) {
      onInvite?.(JSON.parse(String(init?.body ?? '{}')))
      return new Response(JSON.stringify({ ok: true }), { status: 200 })
    }
    return new Response('null', { status: 200 })
  })
}

const ADMIN_ORGS = {
  user: 'alice', is_platform_admin: false,
  memberships: [{ enterprise_id: 'ent-demo', role: 'enterprise-admin' }],
  enterprises: [{ alias: 'ent-demo', display_name: 'Demo 企业' }],
}
const ME = { user: 'alice', username: 'alice', email: 'alice@acme.test', is_platform_admin: false }

it('显示企业 display_name(非 alias)+ 角色,且不渲染不透明 alias', async () => {
  mockApi(ADMIN_ORGS, ME)
  render(<Account />)
  await waitFor(() => expect(screen.getByText('Demo 企业')).toBeTruthy())
  expect(screen.getByText('企业管理员')).toBeTruthy()
  // FR-002b/§1.4:界面绝不渲染不透明 alias
  expect(document.body.textContent).not.toContain('ent-demo')
})

it('enterprise-admin 见邀请入口,提交调用 POST /auth/orgs/invite', async () => {
  const invites: unknown[] = []
  mockApi(ADMIN_ORGS, ME, (b) => invites.push(b))
  render(<Account />)
  await waitFor(() => expect(screen.getByText('Demo 企业')).toBeTruthy())
  const input = screen.getByPlaceholderText(/邮箱/) as HTMLInputElement
  fireEvent.change(input, { target: { value: 'newhire@x.com' } })
  fireEvent.click(screen.getByText('发送邀请'))
  await waitFor(() => expect(invites).toEqual([{ email: 'newhire@x.com' }]))
})

it('member 无邀请入口', async () => {
  const memberOrgs = {
    user: 'bob', is_platform_admin: false,
    memberships: [{ enterprise_id: 'ent-demo', role: 'member' }],
    enterprises: [{ alias: 'ent-demo', display_name: 'Demo 企业' }],
  }
  mockApi(memberOrgs, { user: 'bob', username: 'bob', email: null, is_platform_admin: false })
  render(<Account />)
  await waitFor(() => expect(screen.getByText('Demo 企业')).toBeTruthy())
  expect(screen.queryByText('邀请成员')).toBeNull()
})

it('display_name 为空时回退 alias(诚实降级,不悬空)', async () => {
  const orgs = {
    user: 'carol', is_platform_admin: false,
    memberships: [{ enterprise_id: 'ent-x', role: 'member' }],
    enterprises: [{ alias: 'ent-x', display_name: null }],
  }
  mockApi(orgs, { user: 'carol', username: 'carol', email: null, is_platform_admin: false })
  render(<Account />)
  await waitFor(() => expect(screen.getByText('ent-x')).toBeTruthy())
})
