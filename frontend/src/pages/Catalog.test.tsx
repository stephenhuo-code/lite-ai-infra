import { it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { Catalog } from './Catalog'

// 数据目录 Catalog Explorer 两栏(US3):左树(企业→catalog→schema→数据集,可展开)、右详情。
// 断言:左树渲染 catalog data;点开 data 出 schema datasets;点 schema 后右侧列出两条数据集。
// 禁:详情/权限/策略 Tab、共享/注册/新建 按钮(spec Out);不显 e-/g- 原始 ID(FR-004)。
beforeEach(() => { vi.restoreAllMocks() })
afterEach(() => { vi.restoreAllMocks() })

function mockApis() {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url: any) => {
    const u = String(url)
    if (u === '/v1/catalogs') {
      return new Response(JSON.stringify({ names: ['data'] }), { status: 200 })
    }
    if (u === '/v1/catalogs/data/schemas') {
      return new Response(JSON.stringify({ names: ['datasets'] }), { status: 200 })
    }
    if (u === '/v1/catalogs/data/schemas/datasets/datasets') {
      return new Response(JSON.stringify({
        datasets: [
          {
            name: 'cc3m', enterprise_id: 'e-1', owner: '韩工', scope: 'private',
            location: 'oss://x', format: 'lance', created_at: '2026-06-20T10:00:00Z',
          },
          {
            name: 'laion-clean', enterprise_id: 'e-1', owner: '李工', scope: 'shared',
            location: 'oss://y', format: 'parquet', created_at: '2026-06-19T09:00:00Z',
          },
        ],
      }), { status: 200 })
    }
    return new Response('', { status: 404 })
  })
}

it('左树渲染 catalog;点开出 schema;选中 schema 后右侧列出数据集', async () => {
  mockApis()
  render(<Catalog />)

  // 左树渲染 catalog data
  await waitFor(() => expect(screen.getByText('data')).toBeTruthy())

  // 点开 catalog data → 出 schema datasets
  fireEvent.click(screen.getByText('data'))
  await waitFor(() => expect(screen.getByText('datasets')).toBeTruthy())

  // 点 schema datasets → 右侧详情列出两条数据集(名/格式/owner/scope)
  fireEvent.click(screen.getByText('datasets'))
  await waitFor(() => expect(screen.getByText('cc3m')).toBeTruthy())
  expect(screen.getByText('laion-clean')).toBeTruthy()
  expect(screen.getByText('lance')).toBeTruthy()
  expect(screen.getByText('parquet')).toBeTruthy()
  expect(screen.getAllByText('韩工').length).toBeGreaterThan(0) // owner(列 + 关于此 Schema)
  expect(screen.getByText('李工')).toBeTruthy()
  expect(screen.getByText('已共享')).toBeTruthy() // shared scope

  // 面包屑:Catalog Explorer › data › datasets
  expect(screen.getByText('Catalog Explorer')).toBeTruthy()
})

it('只含 概览 Tab;无 详情/权限/策略 Tab、无 共享/注册/新建 按钮;不显 e-/g- ID', async () => {
  mockApis()
  render(<Catalog />)
  await waitFor(() => expect(screen.getByText('data')).toBeTruthy())
  fireEvent.click(screen.getByText('data'))
  await waitFor(() => expect(screen.getByText('datasets')).toBeTruthy())
  fireEvent.click(screen.getByText('datasets'))
  await waitFor(() => expect(screen.getByText('cc3m')).toBeTruthy())

  // Tab 仅 概览(US3 由概览满足;去掉建设中的「详情」占位)
  expect(screen.getByText('概览')).toBeTruthy()
  expect(screen.queryByText('详情')).toBeNull()

  // 禁:权限/策略 Tab
  expect(screen.queryByText('权限')).toBeNull()
  expect(screen.queryByText('策略')).toBeNull()

  // 禁:共享/注册/新建/添加标签 按钮
  expect(screen.queryByText('共享')).toBeNull()
  expect(screen.queryByText('注册')).toBeNull()
  expect(screen.queryByText('新建')).toBeNull()
  expect(screen.queryByText(/添加标签/)).toBeNull()
  expect(screen.queryByLabelText('新建')).toBeNull()

  // 不显 e-/g- 原始 ID(FR-004):页面文本不含 e-1 / g-1
  expect(screen.queryByText(/e-1/)).toBeNull()
  expect(screen.queryByText(/g-1/)).toBeNull()
})

it('无「详情」Tab 与「建设中」占位(US3 由概览满足)', async () => {
  mockApis()
  render(<Catalog />)
  await waitFor(() => expect(screen.getByText('data')).toBeTruthy())
  fireEvent.click(screen.getByText('data'))
  await waitFor(() => expect(screen.getByText('datasets')).toBeTruthy())
  fireEvent.click(screen.getByText('datasets'))
  await waitFor(() => expect(screen.getByText('cc3m')).toBeTruthy())

  // 「详情」Tab 与建设中占位均已移除
  expect(screen.queryByText('详情')).toBeNull()
  expect(screen.queryByText(/建设中/)).toBeNull()
})

it('展开 schema 的箭头加载其下数据集(树第四层)', async () => {
  mockApis()
  render(<Catalog />)
  await waitFor(() => expect(screen.getByText('data')).toBeTruthy())
  fireEvent.click(screen.getByText('data'))
  await waitFor(() => expect(screen.getByText('datasets')).toBeTruthy())

  // 点 schema 的展开箭头 → 树内出现数据集子项
  fireEvent.click(screen.getByLabelText('展开 datasets'))
  await waitFor(() => {
    // 树里出现 cc3m 子项(此时右侧未选中,故 cc3m 仅来自树)
    expect(screen.getByText('cc3m')).toBeTruthy()
  })
})
