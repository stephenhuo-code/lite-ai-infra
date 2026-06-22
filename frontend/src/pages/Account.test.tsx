import { it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { Account } from './Account'

// Account 角色来自真实 GET /v1/me/orgs 的 memberships[].role,
// 不可用 is_platform_admin 派生。一个 group-admin 的 is_platform_admin=False
// 必须显示「组管理员」,而非「成员」。且界面禁止出现 e-/g- 内部 ID(FR-004)。
beforeEach(() => { vi.restoreAllMocks() })
afterEach(() => { vi.restoreAllMocks() })

it('显示真实组内角色(group-admin → 组管理员),且不渲染 e-/g- ID', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify({
      user: 'alice',
      is_platform_admin: false, // 关键:平台管理员标志为假,但她是组管理员
      memberships: [{ enterprise_id: 'e-1234', group_id: 'g-5678', role: 'group-admin' }],
    }), { status: 200 }),
  )

  render(<Account />)

  // 等真实角色渲染出来
  await waitFor(() => expect(screen.getByText('组管理员')).toBeTruthy())
  // 用户名照常显示(头部 + 「用户」字段各一处)
  expect(screen.getAllByText('alice').length).toBeGreaterThan(0)
  // 不得错显成「成员」(那是 is_platform_admin 派生的 bug)
  expect(screen.queryByText('成员')).toBeNull()
  // FR-004:界面绝不出现 e-/g- 原始 ID
  expect(document.body.textContent).not.toContain('e-1234')
  expect(document.body.textContent).not.toContain('g-5678')
})
