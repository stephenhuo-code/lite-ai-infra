import { api } from './client'
import type { components } from './types-datapipeline'

// 数据准备作业 API（契约 contracts/openapi/data-pipeline.yaml）。
// Job: id/status/terminal/dataset/owner_user/rows_in/rows_written/lance_uri/error。
// JobList: {jobs,total}。PrepareJobRequest: {dataset,source_dataset,np?,process?}
// (catalog-driven:源=已注册的 raw 数据集名 source_dataset,tar_dir 已删 · ADR-023;
//  归属 owner,不再传 group_id · ADR-024)。
export type Job = components['schemas']['Job']
export type JobList = components['schemas']['JobList']
export type PrepareJobRequest = components['schemas']['PrepareJobRequest']

// 列作业（can() 按企业/组过滤）；可选 status 筛选。
export const listJobs = (status?: string): Promise<JobList> =>
  api.get('/v1/data/jobs' + (status ? `?status=${status}` : ''))

// 作业详情。
export const getJob = (id: string): Promise<Job> => api.get(`/v1/data/jobs/${id}`)

// 提交准备作业（源=已注册 raw 数据集 source_dataset）→ 202 返回 job。
export const createJob = (b: PrepareJobRequest): Promise<Job> => api.post('/v1/data/prepare', b)

// 轮询至终态：按 `terminal` 字段判停（FR-007），不做状态串匹配。
export async function pollJob(id: string, opts: { intervalMs?: number } = {}): Promise<Job> {
  const wait = opts.intervalMs ?? 2000
  for (;;) {
    const j = await getJob(id)
    if (j.terminal) return j
    await new Promise(r => setTimeout(r, wait))
  }
}
