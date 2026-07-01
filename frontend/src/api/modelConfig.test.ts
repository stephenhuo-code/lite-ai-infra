import { it, expect, vi, afterEach } from 'vitest'
import { listModelConfig, setModelConfig, clearModelConfig, PROVIDERS } from './modelConfig'

afterEach(() => { vi.restoreAllMocks() })

// listModelConfig:GET /v1/ws/model-config → 解 { providers: [...] }(只回状态,无密钥)。
it('listModelConfig 解出 providers 状态数组', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
    providers: [{ provider: 'anthropic', configured: true, auth_type: 'subscription', has_base_url: false }],
  }), { status: 200 }))
  const r = await listModelConfig()
  expect(r).toEqual([{ provider: 'anthropic', configured: true, auth_type: 'subscription', has_base_url: false }])
})

// setModelConfig:PUT /v1/ws/model-config/{provider},body {auth_type, value}(+ 可选 base_url)。
it('setModelConfig PUT 带 auth_type/value,base_url 仅非空下发', async () => {
  let url = ''; let method = ''; let body: any = null
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (u: any, init?: any) => {
    url = String(u); method = init?.method; body = JSON.parse(init.body)
    return new Response(JSON.stringify({}), { status: 200 })
  })
  await setModelConfig('openai', { auth_type: 'api_key', value: '  sk-abc  ', base_url: ' https://x.test ' })
  expect(url).toBe('/v1/ws/model-config/openai')
  expect(method).toBe('PUT')
  expect(body.auth_type).toBe('api_key')
  expect(body.value).toBe('sk-abc')
  expect(body.base_url).toBe('https://x.test')
})

it('setModelConfig:空 base_url 不下发', async () => {
  let body: any = null
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (_u: any, init?: any) => {
    body = JSON.parse(init.body)
    return new Response(JSON.stringify({}), { status: 200 })
  })
  await setModelConfig('gemini', { auth_type: 'api_key', value: 'k' })
  expect('base_url' in body).toBe(false)
})

// clearModelConfig:DELETE /v1/ws/model-config/{provider}。
it('clearModelConfig DELETE 到 /v1/ws/model-config/{provider}', async () => {
  let url = ''; let method = ''
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (u: any, init?: any) => {
    url = String(u); method = init?.method
    return new Response(JSON.stringify({}), { status: 200 })
  })
  await clearModelConfig('anthropic')
  expect(url).toBe('/v1/ws/model-config/anthropic')
  expect(method).toBe('DELETE')
})

// provider 定义表镜像 BFF:gemini 无 base_url;anthropic/openai 支持。
it('PROVIDERS 表:auth 选项与 base_url 支持', () => {
  const g = PROVIDERS.find(p => p.provider === 'gemini')!
  expect(g.authOptions).toEqual(['api_key'])
  expect(g.supportsBaseUrl).toBe(false)
  const a = PROVIDERS.find(p => p.provider === 'anthropic')!
  expect(a.authOptions).toEqual(['subscription', 'api_key'])
  expect(a.supportsBaseUrl).toBe(true)
})
