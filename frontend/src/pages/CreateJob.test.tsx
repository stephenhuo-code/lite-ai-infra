import { it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { CreateJob } from './CreateJob'

// 创建作业页(catalog-driven · ADR-023 / owner 模型 · ADR-024):
// 挂载拉 listDatasets()→ 过滤 kind==='raw'→ 源下拉只列 raw;
// 提交 POST /v1/data/prepare body {dataset,source_dataset} 且无 group_id / tar_dir。
beforeEach(() => { vi.restoreAllMocks() })
afterEach(() => { vi.restoreAllMocks() })

// 记录最后一次 /v1/data/prepare 的请求体,供断言。
let lastPrepareBody: any = null

function mockApis() {
  lastPrepareBody = null
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url: any, init?: any) => {
    const u = String(url)
    if (u === '/v1/catalogs/data/schemas/datasets/datasets' && (!init || init.method === 'GET' || !init.method)) {
      return new Response(JSON.stringify({
        datasets: [
          { name: 'coco', enterprise_id: 'e-1', owner: 'u-1', scope: 'private', location: 'oss://x', kind: 'raw' },
          { name: 'coco-clean', enterprise_id: 'e-1', owner: 'u-1', scope: 'private', location: 'lance://y', kind: 'processed' },
        ],
      }), { status: 200 })
    }
    if (u === '/v1/data/prepare' && init?.method === 'POST') {
      lastPrepareBody = JSON.parse(init.body)
      return new Response(JSON.stringify({
        id: 'job-1', status: 'queued', terminal: false, dataset: lastPrepareBody.dataset,
        owner_user: 'u-1', enterprise_id: 'e-1',
      }), { status: 202 })
    }
    return new Response('', { status: 404 })
  })
}

function renderPage() {
  return render(<MemoryRouter><CreateJob /></MemoryRouter>)
}

it('源下拉只列 kind=raw 的数据集(coco),不列 processed(coco-clean)', async () => {
  mockApis()
  renderPage()

  const select = screen.getByLabelText('源数据集') as HTMLSelectElement
  await waitFor(() => expect(within_options(select)).toContain('coco'))
  // 只列 raw:coco 在,processed 的 coco-clean 不在
  expect(within_options(select)).toContain('coco')
  expect(within_options(select)).not.toContain('coco-clean')
})

it('选源 + 填产出名 + 提交 → POST body {dataset,source_dataset} 且无 group_id / tar_dir', async () => {
  mockApis()
  renderPage()

  const select = screen.getByLabelText('源数据集') as HTMLSelectElement
  await waitFor(() => expect(within_options(select)).toContain('coco'))

  fireEvent.change(select, { target: { value: 'coco' } })
  fireEvent.change(screen.getByLabelText('产出数据集名'), { target: { value: 'coco-clean' } })

  fireEvent.click(screen.getByRole('button', { name: '提交作业' }))

  await waitFor(() => expect(lastPrepareBody).not.toBeNull())
  expect(lastPrepareBody.dataset).toBe('coco-clean')
  expect(lastPrepareBody.source_dataset).toBe('coco')
  // group_id 已删(owner 模型 · ADR-024),tar_dir 已删,均不得出现在 body
  expect('group_id' in lastPrepareBody).toBe(false)
  expect('tar_dir' in lastPrepareBody).toBe(false)
})

it('未选源时不可提交(canSubmit 判 source)', async () => {
  mockApis()
  renderPage()
  await waitFor(() => expect((screen.getByLabelText('源数据集') as HTMLSelectElement).options.length).toBeGreaterThan(1))

  // 只填产出名、不选源 → 提交按钮 disabled
  fireEvent.change(screen.getByLabelText('产出数据集名'), { target: { value: 'coco-clean' } })
  expect((screen.getByRole('button', { name: '提交作业' }) as HTMLButtonElement).disabled).toBe(true)
})

// 取 select 的 option 文本数组。
function within_options(select: HTMLSelectElement): string[] {
  return Array.from(select.options).map(o => o.textContent ?? '')
}
