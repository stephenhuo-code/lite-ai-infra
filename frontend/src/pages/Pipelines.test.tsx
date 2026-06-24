import { it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'
import { Pipelines } from './Pipelines'
import * as jobsApi from '../api/jobs'
import type { Job } from '../api/jobs'

// 数据管线页(US4 跟踪 / US5 排障)。
// 列 = 作业ID/数据集/状态徽章/行数(出/入)/创建。状态筛选 全部/运行中/已完成/失败。
// US5 可证伪:按「失败」筛选只剩 failed 那条;进 failed 详情显示其 error 文本。
beforeEach(() => { vi.restoreAllMocks() })
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks() })  // useRealTimers 兜底:防 fake timers 泄漏到下个测试

const FAILED: Job = {
  id: 'job-fail', status: 'failed', terminal: true, dataset: 'cc3m-bad',
  owner_user: 'u-1', enterprise_id: 'e-1', rows_in: 100, rows_written: 0,
  error: 'tar 解包失败:坏文件 0007.tar', created_at: '2026-06-14T08:00:00Z',
}
const RUNNING: Job = {
  id: 'job-run', status: 'running', terminal: false, dataset: 'cc3m-run',
  owner_user: 'u-1', enterprise_id: 'e-1', rows_in: null, rows_written: null,
  created_at: '2026-06-14T09:00:00Z',
}
const SUCCEEDED: Job = {
  id: 'job-ok', status: 'succeeded', terminal: true, dataset: 'cc3m-ok',
  owner_user: 'u-1', enterprise_id: 'e-1', rows_in: 200, rows_written: 200,
  lance_uri: 'lance://out/cc3m-ok', source_dataset: 'coco', created_at: '2026-06-14T07:00:00Z',
}

// listJobs 按 status 返回:无 status = 全部三条;status==='failed' = 仅 failed。
function mockList() {
  vi.spyOn(jobsApi, 'listJobs').mockImplementation(async (status?: string) => {
    const all = [FAILED, RUNNING, SUCCEEDED]
    const filtered = status ? all.filter(j => j.status === status) : all
    return { jobs: filtered, total: filtered.length }
  })
}

it('按「失败」筛选只剩 failed 那条', async () => {
  mockList()
  render(<Pipelines />)

  // 默认全部:三条都在
  await waitFor(() => expect(screen.getByText('cc3m-bad')).toBeTruthy())
  expect(screen.getByText('cc3m-run')).toBeTruthy()
  expect(screen.getByText('cc3m-ok')).toBeTruthy()

  // 点「失败」筛选(US5)→ listJobs('failed') → 只剩 failed 那条
  fireEvent.click(screen.getByRole('button', { name: '失败' }))
  await waitFor(() => expect(screen.queryByText('cc3m-ok')).toBeNull())
  expect(screen.queryByText('cc3m-run')).toBeNull()
  expect(screen.getByText('cc3m-bad')).toBeTruthy()
  expect(jobsApi.listJobs).toHaveBeenCalledWith('failed')
})

it('进 failed 详情显示其 error 文本(US5 可证伪)', async () => {
  mockList()
  vi.spyOn(jobsApi, 'getJob').mockResolvedValue(FAILED)
  render(<Pipelines />)

  await waitFor(() => expect(screen.getByText('cc3m-bad')).toBeTruthy())
  // 点 failed 那行进详情
  fireEvent.click(screen.getByText('cc3m-bad').closest('tr')!)

  // 详情显示 error 文本
  await waitFor(() => expect(screen.getByText('tar 解包失败:坏文件 0007.tar')).toBeTruthy())
  expect(screen.getByText('失败原因')).toBeTruthy()
})

it('succeeded 详情展示产物 lance_uri', async () => {
  mockList()
  vi.spyOn(jobsApi, 'getJob').mockResolvedValue(SUCCEEDED)
  render(<Pipelines />)

  await waitFor(() => expect(screen.getByText('cc3m-ok')).toBeTruthy())
  fireEvent.click(screen.getByText('cc3m-ok').closest('tr')!)

  await waitFor(() => expect(screen.getByText('lance://out/cc3m-ok')).toBeTruthy())
})

it('succeeded 详情「注册产物」→ POST body kind=processed/format=lance/location=lance_uri/num_samples=rows_written;样本数只读', async () => {
  mockList()
  vi.spyOn(jobsApi, 'getJob').mockResolvedValue(SUCCEEDED)
  // registerDataset 走真实 api client(fetch);拦截 catalog POST 记录 body。
  let registerBody: any = null
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url: any, init?: any) => {
    const u = String(url)
    if (u === '/v1/catalogs/data/schemas/datasets/datasets' && init?.method === 'POST') {
      registerBody = JSON.parse(init.body)
      return new Response(JSON.stringify({ name: registerBody.name, enterprise_id: 'e-1', owner: 'u-1', scope: 'private', location: registerBody.location, kind: 'processed' }), { status: 201 })
    }
    return new Response('', { status: 404 })
  })

  render(<Pipelines />)
  await waitFor(() => expect(screen.getByText('cc3m-ok')).toBeTruthy())
  fireEvent.click(screen.getByText('cc3m-ok').closest('tr')!)

  // 样本数取自 job.rows_written(200)只读展示(非输入框)
  await waitFor(() => expect(screen.getByText('样本数(取自作业,不可编辑)')).toBeTruthy())
  const drawer = screen.getByText('作业详情').closest('div')!.parentElement!
  expect(within(drawer).queryByRole('spinbutton')).toBeNull() // 无 number 输入框
  expect(within(drawer).queryByRole('textbox')).toBeNull()    // 无文本输入框

  fireEvent.click(screen.getByRole('button', { name: '注册产物' }))
  await waitFor(() => expect(registerBody).not.toBeNull())
  expect(registerBody.kind).toBe('processed')
  expect(registerBody.format).toBe('lance')
  expect(registerBody.location).toBe('lance://out/cc3m-ok') // = job.lance_uri
  expect(registerBody.num_samples).toBe(200)                // = job.rows_written
  expect(registerBody.derived_from).toBe('coco')            // = job.source_dataset(真实来源,非产出名 cc3m-ok)
})

it('succeeded 详情含二次处理占位(禁用,不给会失败入口 · US3-AC3)', async () => {
  mockList()
  vi.spyOn(jobsApi, 'getJob').mockResolvedValue(SUCCEEDED)
  render(<Pipelines />)
  await waitFor(() => expect(screen.getByText('cc3m-ok')).toBeTruthy())
  fireEvent.click(screen.getByText('cc3m-ok').closest('tr')!)

  const btn = await screen.findByText(/再处理/)
  expect((btn as HTMLButtonElement).disabled).toBe(true)
})

it('列表自动轮询:运行中作业跑完后列表自动翻「已完成」(无需手刷)', async () => {
  const runJob: Job = { ...RUNNING, id: 'job-poll', dataset: 'coco-poll' }
  const doneJob: Job = { ...runJob, status: 'succeeded', terminal: true, rows_in: 64, rows_written: 64 }
  let calls = 0
  // 首拉返回运行中 → 列表起轮询;之后每次返回 succeeded → 行内徽章自动翻终态。
  vi.spyOn(jobsApi, 'listJobs').mockImplementation(async () => {
    calls++
    return { jobs: [calls === 1 ? runJob : doneJob], total: 1 }
  })
  render(<Pipelines />)

  // 初次:行内状态徽章=运行中(within 避开同名筛选按钮「运行中」)
  await waitFor(() => expect(within(screen.getByText('coco-poll').closest('tr')!).getByText('运行中')).toBeTruthy())

  // 一个 2.5s 轮询周期后自动重拉 → 行内徽章翻「已完成」(timeout 跨过周期)
  await waitFor(
    () => expect(within(screen.getByText('coco-poll').closest('tr')!).getByText('已完成')).toBeTruthy(),
    { timeout: 4000 },
  )
  expect(within(screen.getByText('coco-poll').closest('tr')!).queryByText('运行中')).toBeNull()
  expect(calls).toBeGreaterThanOrEqual(2)  // 确实重拉过(非一次性快照)
})

it('运行中作业进详情走 pollJob 轮询至终态', async () => {
  mockList()
  // 首次 getJob 返回运行中(非终态)→ 触发 pollJob;pollJob 解析为终态(产物)。
  const done = { ...RUNNING, status: 'succeeded' as const, terminal: true, lance_uri: 'lance://out/run-done' }
  vi.spyOn(jobsApi, 'getJob').mockResolvedValue(RUNNING)
  const pollSpy = vi.spyOn(jobsApi, 'pollJob').mockResolvedValue(done)
  render(<Pipelines />)

  await waitFor(() => expect(screen.getByText('cc3m-run')).toBeTruthy())
  fireEvent.click(screen.getByText('cc3m-run').closest('tr')!)

  // 非终态作业必须触发 pollJob 轮询(FR-007)
  await waitFor(() => expect(pollSpy).toHaveBeenCalledWith('job-run'))
  // 轮询到终态后展示产物
  await waitFor(() => expect(screen.getByText('lance://out/run-done')).toBeTruthy())
  // 详情面板里也出现 succeeded 徽章
  const drawer = screen.getByText('作业详情').closest('div')!.parentElement!
  expect(within(drawer).getAllByText('已完成').length).toBeGreaterThan(0)
})
