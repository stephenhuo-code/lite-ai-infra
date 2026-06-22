import { it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'
import { Datasets } from './Datasets'

// 数据集页:列表 = metadata 已处理数据集 + Plan7 原始数据合并。
// 列 = 名称/描述/格式/样本数/大小/创建人/操作。缺值显「—」不报错(FR-008)。
// 禁出现 模态/标签/用户组 表头(FR-012 + 组织模型)。搜索按名称过滤。
beforeEach(() => { vi.restoreAllMocks() })
afterEach(() => { vi.restoreAllMocks() })

function mockApis() {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url: any) => {
    const u = String(url)
    if (u === '/v1/catalogs/data/schemas/datasets/datasets') {
      return new Response(JSON.stringify({
        datasets: [
          // 一条含 format/num_samples/size_bytes/created_by
          {
            name: 'cc3m-clean', enterprise_id: 'e-1', group_id: 'g-1', scope: 'private',
            location: 'lance://x', comment: '清洗后', created_by: '韩工',
            format: 'lance', num_samples: 3300000, size_bytes: 1288490188,
          },
          // 一条 num_samples=null(缺值显 —)
          {
            name: 'docs-partial', enterprise_id: 'e-1', group_id: 'g-1', scope: 'private',
            location: 'lance://y', comment: null, created_by: null,
            format: 'parquet', num_samples: null, size_bytes: null,
          },
        ],
      }), { status: 200 })
    }
    if (u === '/v1/data/raw') {
      return new Response(JSON.stringify({
        raw: [
          {
            id: 'raw-9', name: 'docs-pdf', group_id: 'g-1', enterprise_id: 'e-1',
            oss_key: 'e/g/raw/x', status: 'ready', size: 335544320,
          },
        ],
        total: 1,
      }), { status: 200 })
    }
    return new Response('', { status: 404 })
  })
}

it('渲染名称/格式/样本数/大小/创建人;null 显「—」;无 模态/标签/用户组 表头', async () => {
  mockApis()
  render(<Datasets />)

  // metadata 行渲染
  await waitFor(() => expect(screen.getByText('cc3m-clean')).toBeTruthy())
  expect(screen.getByText('lance')).toBeTruthy()
  expect(screen.getByText('3,300,000')).toBeTruthy() // 样本数
  expect(screen.getByText('1.2 GB')).toBeTruthy()    // 大小
  expect(screen.getByText('韩工')).toBeTruthy()       // 创建人

  // 原始行渲染并标「原始」(格式列 + 名称旁徽标各一处)
  expect(screen.getByText('docs-pdf')).toBeTruthy()
  const rawRow = screen.getByText('docs-pdf').closest('tr')!
  expect(within(rawRow).getAllByText('原始').length).toBeGreaterThan(0)

  // 缺值显「—」不报错:docs-partial 的 num_samples=null、created_by=null
  const partialRow = screen.getByText('docs-partial').closest('tr')!
  expect(within(partialRow).getAllByText('—').length).toBeGreaterThan(0)

  // 禁出现 模态/标签/用户组 表头(FR-012 + 组织模型)
  expect(screen.queryByText('模态')).toBeNull()
  expect(screen.queryByText('标签')).toBeNull()
  expect(screen.queryByText('用户组')).toBeNull()
})

it('搜索框按名称过滤', async () => {
  mockApis()
  render(<Datasets />)
  await waitFor(() => expect(screen.getByText('cc3m-clean')).toBeTruthy())

  fireEvent.change(screen.getByLabelText('搜索数据集名称'), { target: { value: 'cc3m' } })

  expect(screen.getByText('cc3m-clean')).toBeTruthy()
  expect(screen.queryByText('docs-partial')).toBeNull()
  expect(screen.queryByText('docs-pdf')).toBeNull()
})
