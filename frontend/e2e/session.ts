import { execSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

// frontend/e2e/ → 上两级 = 仓库根(mint-session.py 从 repo root 跑,需 import services.*)。
const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..')

// browserless 造真 BFF 会话 cookie(复用 Plan 6 SessionCodec):ROPC 拿真 KC token → 加密成 cookie。
// 返回 {cookie, session, csrf},供 context.addCookies 注入,免在浏览器走 OIDC。
export function mintSession(): { cookie: string; session: string; csrf: string } {
  const out = execSync('uv run python frontend/scripts/mint-session.py', {
    cwd: repoRoot,
    encoding: 'utf8',
  })
  return JSON.parse(out)
}
