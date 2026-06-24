import { it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'
import { Datasets } from './Datasets'

// 记录最后一次 catalog POST(注册)的请求体,供断言。
let lastRegisterBody: any = null

// 数据集页:列表 = metadata 已处理数据集 + Plan7 原始数据合并。
// 列 = 名称/描述/格式/样本数/大小/创建人/操作。缺值显「—」不报错(FR-008)。
// 禁出现 模态/标签/用户组 表头(FR-012 + 组织模型)。搜索按名称过滤。
beforeEach(() => { vi.restoreAllMocks() })
afterEach(() => { vi.restoreAllMocks() })

function mockApis() {
  lastRegisterBody = null
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url: any, init?: any) => {
    const u = String(url)
    if (u === '/v1/catalogs/data/schemas/datasets/datasets' && init?.method === 'POST') {
      lastRegisterBody = JSON.parse(init.body)
      return new Response(JSON.stringify({
        name: lastRegisterBody.name, enterprise_id: 'e-1', owner: 'u-1',
        scope: 'private', location: 'oss://e/g/raw', kind: 'raw',
      }), { status: 201 })
    }
    if (u === '/v1/catalogs/data/schemas/datasets/datasets') {
      return new Response(JSON.stringify({
        datasets: [
          // 已处理:含 kind=processed + derived_from(血缘)
          {
            name: 'cc3m-clean', enterprise_id: 'e-1', owner: 'u-1', scope: 'private',
            location: 'lance://x', comment: '清洗后', created_by: '韩工',
            format: 'lance', num_samples: 3300000, size_bytes: 1288490188,
            kind: 'processed', derived_from: 'cc3m-raw',
          },
          // 已处理 + num_samples=null + created_by=null:创建人回退到 owner 字段
          {
            name: 'docs-partial', enterprise_id: 'e-1', owner: '李工', scope: 'private',
            location: 'lance://y', comment: null, created_by: null,
            format: 'parquet', num_samples: null, size_bytes: null,
            kind: 'processed', derived_from: null,
          },
        ],
      }), { status: 200 })
    }
    if (u === '/v1/data/raw') {
      return new Response(JSON.stringify({
        raw: [
          {
            id: 'raw-9', name: 'docs-pdf', owner_user: '王工', enterprise_id: 'e-1',
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

  // 创建人列 = owner 优先(owner 模型 · ADR-024;Gravitino created_by 可能是 anonymous):
  // cc3m-clean owner='u-1' 优先于 created_by='韩工';原始上传显 owner_user(王工);created_by 缺失回退 owner(李工)。
  expect(within(screen.getByText('cc3m-clean').closest('tr')!).getByText('u-1')).toBeTruthy() // owner 优先于 created_by
  expect(screen.queryByText('韩工')).toBeNull()       // created_by 不再优先展示
  const partialRowOwner = screen.getByText('docs-partial').closest('tr')!
  expect(within(partialRowOwner).getByText('李工')).toBeTruthy() // owner 回退

  // 原始行渲染并标「原始」(格式列 + 名称旁徽标各一处)+ 显 owner(王工)
  expect(screen.getByText('docs-pdf')).toBeTruthy()
  const rawRow = screen.getByText('docs-pdf').closest('tr')!
  expect(within(rawRow).getAllByText('原始').length).toBeGreaterThan(0)
  expect(within(rawRow).getByText('王工')).toBeTruthy() // owner_user

  // 缺值显「—」不报错:docs-partial 的 num_samples=null、created_by=null
  const partialRow = screen.getByText('docs-partial').closest('tr')!
  expect(within(partialRow).getAllByText('—').length).toBeGreaterThan(0)

  // 禁出现 模态/标签/用户组 表头(FR-012 + 组织模型)
  expect(screen.queryByText('模态')).toBeNull()
  expect(screen.queryByText('标签')).toBeNull()
  expect(screen.queryByText('用户组')).toBeNull()
})

it('注册=状态流转:同名原始上传并入 catalog 行(单行、补大小、owner 创建人),不重复两行', async () => {
  // catalog 有已注册的 raw 数据集 coco(无大小、created_by=anonymous),
  // raw 存储也有同名上传 coco(3.3MB)。应合并成一行,而非两行。
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url: any) => {
    const u = String(url)
    if (u === '/v1/catalogs/data/schemas/datasets/datasets') {
      return new Response(JSON.stringify({
        datasets: [{
          name: 'coco', enterprise_id: 'e-1', owner: 'u-sub', scope: 'private',
          location: 's3a://b/raw/coco', comment: null, created_by: 'anonymous',
          format: 'webdataset', num_samples: null, size_bytes: null, kind: 'raw', derived_from: null,
        }],
      }), { status: 200 })
    }
    if (u === '/v1/data/raw') {
      return new Response(JSON.stringify({
        raw: [{ id: 'raw-1', name: 'coco', owner_user: 'u-sub', enterprise_id: 'e-1',
                oss_key: 'e/raw/coco', status: 'ready', size: 3460000 }],
        total: 1,
      }), { status: 200 })
    }
    return new Response('', { status: 404 })
  })
  render(<Datasets />)
  await waitFor(() => expect(screen.getByText('coco')).toBeTruthy())

  // 只有一行 coco(并入,非重复两行)
  const cocoRows = new Set(screen.getAllByText('coco').map(el => el.closest('tr')))
  expect(cocoRows.size).toBe(1)

  const row = screen.getByText('coco').closest('tr')! as HTMLElement
  expect(within(row).getByText('3.3 MB')).toBeTruthy()            // 大小来自原始上传
  expect(within(row).getByText('u-sub')).toBeTruthy()            // 创建人=owner
  expect(within(row).queryByText('anonymous')).toBeNull()        // 不显 Gravitino creator
  expect(within(row).queryByText('注册到目录')).toBeNull()        // 已注册 → 无注册按钮
})

it('点详情打开侧抽屉,展示 location/scope 等已有字段,不显 e-/g- 内部 ID(US1 AC4 / FR-004)', async () => {
  mockApis()
  render(<Datasets />)
  await waitFor(() => expect(screen.getByText('cc3m-clean')).toBeTruthy())

  // 点该行的「详情」按钮
  const row = screen.getByText('cc3m-clean').closest('tr')!
  fireEvent.click(within(row).getByText('详情'))

  // 抽屉打开:标题 + 已有字段(位置/是否共享)
  const drawer = await screen.findByText('数据集详情')
  const panel = drawer.closest('div.relative')!
  expect(within(panel as HTMLElement).getByText('位置')).toBeTruthy()
  expect(within(panel as HTMLElement).getByText('lance://x')).toBeTruthy() // location
  expect(within(panel as HTMLElement).getByText('是否共享')).toBeTruthy()
  expect(within(panel as HTMLElement).getByText('私有')).toBeTruthy()       // scope=private
  expect(within(panel as HTMLElement).getByText('清洗后')).toBeTruthy()     // 描述

  // 不暴露 e-/g- 内部 ID(FR-004)
  expect(within(panel as HTMLElement).queryByText('e-1')).toBeNull()
  expect(within(panel as HTMLElement).queryByText('g-1')).toBeNull()
})

it('原始数据详情抽屉显状态字段', async () => {
  mockApis()
  render(<Datasets />)
  await waitFor(() => expect(screen.getByText('docs-pdf')).toBeTruthy())

  const row = screen.getByText('docs-pdf').closest('tr')!
  fireEvent.click(within(row).getByText('详情'))

  const drawer = await screen.findByText('数据集详情')
  const panel = drawer.closest('div.relative')! as HTMLElement
  expect(within(panel).getByText('状态')).toBeTruthy()
  expect(within(panel).getByText('就绪')).toBeTruthy() // status=ready
})

it('列表渲染 kind 中文(已处理);已处理详情显血缘来源 derived_from', async () => {
  mockApis()
  render(<Datasets />)
  await waitFor(() => expect(screen.getByText('cc3m-clean')).toBeTruthy())

  // 列表「类型」列:已处理项显「已处理」、原始上传项显「原始」
  const procRow = screen.getByText('cc3m-clean').closest('tr')!
  expect(within(procRow).getByText('已处理')).toBeTruthy()
  const rawRow = screen.getByText('docs-pdf').closest('tr')!
  expect(within(rawRow).getAllByText('原始').length).toBeGreaterThan(0)

  // 详情抽屉:已处理项显「来源」+ derived_from 值
  fireEvent.click(within(procRow).getByText('详情'))
  const drawer = await screen.findByText('数据集详情')
  const panel = drawer.closest('div.relative')! as HTMLElement
  expect(within(panel).getByText('来源')).toBeTruthy()
  expect(within(panel).getByText('cc3m-raw')).toBeTruthy()
  expect(within(panel).getByText('已处理')).toBeTruthy() // 类型字段
})

it('原始上传项(ready,未在 catalog)点「注册到目录」→ POST body kind=raw 且无 location', async () => {
  mockApis()
  render(<Datasets />)
  await waitFor(() => expect(screen.getByText('docs-pdf')).toBeTruthy())

  const rawRow = screen.getByText('docs-pdf').closest('tr')!
  fireEvent.click(within(rawRow).getByText('注册到目录'))

  await waitFor(() => expect(lastRegisterBody).not.toBeNull())
  expect(lastRegisterBody.name).toBe('docs-pdf')
  expect(lastRegisterBody.kind).toBe('raw')
  // group_id 已删(owner 模型 · ADR-024),不得出现在注册 body
  expect('group_id' in lastRegisterBody).toBe(false)
  // raw 注册不带 location(服务端钉死)
  expect(lastRegisterBody.location ?? null).toBeNull()
})

it('已处理数据集不显「注册到目录」(只有原始上传 ready 项可注册)', async () => {
  mockApis()
  render(<Datasets />)
  await waitFor(() => expect(screen.getByText('cc3m-clean')).toBeTruthy())

  const procRow = screen.getByText('cc3m-clean').closest('tr')!
  expect(within(procRow).queryByText('注册到目录')).toBeNull()
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
