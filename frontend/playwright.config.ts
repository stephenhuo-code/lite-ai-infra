import { defineConfig, devices } from '@playwright/test'

// Playwright 真浏览器 e2e(Plan 8b Task7)。
// 真拓扑:gateway serve dist(:8090)同源拿到前端 + 调 BFF(非 vite dev)。
// 会话用 Plan 6 SessionCodec browserless 注入(e2e/session.ts → scripts/mint-session.py),免在浏览器走 OIDC。
// 活体运行前置:make dev-up → make fe-build → make run-gateway(详见计划文件 Task7 Step5 runbook)。
export default defineConfig({
  testDir: 'e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: 'list',
  use: {
    // 真拓扑默认 :8090(make run-gateway serve dist)。CI/本地可用 E2E_BASE_URL 覆盖端口。
    baseURL: process.env.E2E_BASE_URL || 'http://localhost:8090',
    trace: 'on-first-retry',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
})
