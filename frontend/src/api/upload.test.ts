import { describe, it, expect, vi } from 'vitest'
import { uploadDataset } from './upload'
describe('uploadDataset', () => {
it('走 请求上传→PUT OSS(直连,非同源)→complete 三段', async () => {
  const calls: string[] = []
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url: any, init: any) => {
    calls.push(`${init?.method ?? 'GET'} ${url}`)
    if (String(url) === '/v1/data/raw') return new Response(JSON.stringify({raw_id:'raw-1', url:'https://oss.test/k?sig', oss_key:'e/g/raw/x'}), {status:200})
    if (String(url).startsWith('https://oss.test')) return new Response('', {status:200})
    if (String(url) === '/v1/data/raw/raw-1/complete') return new Response(JSON.stringify({status:'ready'}), {status:200})
    return new Response('', {status:404})
  })
  const out = await uploadDataset({ dataset:'cc3m', filename:'a.bin', file: new Blob(['x']) }, ()=>{})
  expect(out.status).toBe('ready')
  expect(calls).toEqual(['POST /v1/data/raw', 'PUT https://oss.test/k?sig', 'POST /v1/data/raw/raw-1/complete'])
})
})
