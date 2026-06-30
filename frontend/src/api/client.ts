// 同源 API 客户端(ADR-019):前端不持 token,凭 BFF HttpOnly 会话 cookie。
// 变更请求双提交 CSRF(读非-HttpOnly csrf_token cookie → 加 X-CSRF-Token 头);401 → 跳 /auth/login。
export function csrfFromCookie(): string {
  return document.cookie.split('; ').find(c => c.startsWith('csrf_token='))?.split('=')[1] ?? ''
}
const MUT = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])
async function req(method: string, path: string, body?: unknown) {
  const headers: Record<string, string> = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (MUT.has(method)) headers['X-CSRF-Token'] = csrfFromCookie()
  const res = await fetch(path, { method, credentials: 'include', headers,
    body: body !== undefined ? JSON.stringify(body) : undefined })
  if (res.status === 401) { window.location.assign('/auth/login'); throw new Error('unauthenticated') }
  if (!res.ok) throw new Error(`${res.status}`)
  return res.status === 204 ? null : res.json()
}
export const api = {
  get: (p: string) => req('GET', p),
  post: (p: string, b?: unknown) => req('POST', p, b),
  put: (p: string, b?: unknown) => req('PUT', p, b),
}
