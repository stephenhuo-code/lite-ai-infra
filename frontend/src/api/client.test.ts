import { describe, it, expect, vi, beforeEach } from 'vitest'
import { api, csrfFromCookie } from './client'
beforeEach(() => { document.cookie = 'csrf_token=tok123'; vi.restoreAllMocks() })
describe('api client', () => {
  it('GET 同源、带 credentials', async () => {
    const f = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ok:1}), {status:200}))
    await api.get('/v1/data/jobs')
    expect(f).toHaveBeenCalledWith('/v1/data/jobs', expect.objectContaining({ credentials: 'include' }))
  })
  it('变更请求自动带 X-CSRF-Token(取自 cookie)', async () => {
    const f = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}', {status:202}))
    await api.post('/v1/data/prepare', { a: 1 })
    const init = f.mock.calls[0][1]!
    expect((init.headers as any)['X-CSRF-Token']).toBe('tok123')
  })
  it('401 → 跳 /auth/login', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('unauth', {status:401}))
    const assign = vi.fn(); Object.defineProperty(window, 'location', { value: { assign, href:'' }, writable:true })
    await expect(api.get('/v1/me/orgs')).rejects.toBeTruthy()
    expect(assign).toHaveBeenCalledWith('/auth/login')
  })
})
// csrfFromCookie 在 client.ts 导出供组件复用(如 logout)
void csrfFromCookie
