import { test, expect } from '@playwright/test'
import { mintSession } from './session'

// 数据域核心流(真浏览器 + 真 BFF 会话,经 gateway serve dist 同源调真服务)。
// 会话用 Plan 6 SessionCodec browserless 注入(免 OIDC):mint-session.py → addCookies。
// 断言用 role/唯一文案,避开 strict-mode 多匹配(如 '数据集' 同时命中导航与「上传数据集」按钮)。
test('数据域核心流:注入会话→数据集→数据目录→数据管线→账户', async ({ context, page }) => {
  const s = mintSession()
  await context.addCookies([
    { name: s.cookie, value: s.session, domain: 'localhost', path: '/' },
    { name: 'csrf_token', value: s.csrf, domain: 'localhost', path: '/' },
  ])

  // US1:登录态进数据集页(「上传数据集」按钮是数据集页独有,稳定可见)
  await page.goto('/datasets')
  await expect(page.getByRole('button', { name: '上传数据集' })).toBeVisible()

  // US3:数据目录
  await page.getByRole('link', { name: '数据目录' }).click()
  await expect(page).toHaveURL(/catalog/)

  // US4/US5:数据管线
  await page.getByRole('link', { name: '数据管线' }).click()
  await expect(page).toHaveURL(/pipelines/)

  // US6:我的账户(「角色」是账户页 <dt>,唯一)
  await page.getByRole('link', { name: '我的账户' }).click()
  await expect(page).toHaveURL(/account/)
  await expect(page.getByText('角色', { exact: false })).toBeVisible()
})
