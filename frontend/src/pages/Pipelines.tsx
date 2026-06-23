import { useCallback, useEffect, useState } from 'react'
import { listJobs, getJob, pollJob } from '../api/jobs'
import type { Job } from '../api/jobs'
import { registerDataset } from '../api/datasets'

// 数据管线页(US4 跟踪 / US5 排障)。
// 作业表:ID / 数据集 / 状态徽章 / 行数(出/入) / 创建。
// 状态筛选:全部 / 运行中 / 已完成 / 失败(US5=失败筛选 + 详情看 error)。
// 点行进详情:运行中作业用 pollJob 轮询至终态;终态展示产物 lance_uri / 失败 error。
// 终态判断按 `terminal` 字段(非状态串匹配,FR-007)。缺值显「—」不报错。
// 视觉照高保真原型 2026-06-22-data-domain-hifi.html 数据管线段(靛蓝 #6366F1)。

const BRAND = '#6366F1'

// 筛选项:value 为空 = 全部(不传 status)。
const FILTERS: { label: string; value: string }[] = [
  { label: '全部', value: '' },
  { label: '运行中', value: 'running' },
  { label: '已完成', value: 'succeeded' },
  { label: '失败', value: 'failed' },
]

function dash(v: string | number | null | undefined): string {
  return v === null || v === undefined || v === '' ? '—' : String(v)
}

function fmtNum(n: number | null | undefined): string {
  return n === null || n === undefined ? '—' : n.toLocaleString('en-US')
}

function fmtDate(v: string | null | undefined): string {
  if (!v) return '—'
  return v.length >= 16 ? v.slice(0, 16).replace('T', ' ') : v
}

// 状态徽章:queued/running(带脉冲)/succeeded(绿)/failed(红)。
function StatusBadge({ status }: { status: Job['status'] }) {
  const map: Record<Job['status'], { text: string; cls: string; dot: string; pulse?: boolean }> = {
    queued: { text: '排队中', cls: 'bg-slate-100 text-slate-600', dot: 'bg-slate-400' },
    running: { text: '运行中', cls: 'bg-blue-50 text-blue-700', dot: 'bg-blue-500', pulse: true },
    succeeded: { text: '已完成', cls: 'bg-emerald-50 text-emerald-700', dot: 'bg-emerald-500' },
    failed: { text: '失败', cls: 'bg-red-50 text-red-700', dot: 'bg-red-500' },
  }
  const s = map[status] ?? map.queued
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full ${s.cls}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${s.dot} ${s.pulse ? 'animate-pulse' : ''}`} />
      {s.text}
    </span>
  )
}

// 作业详情侧抽屉:运行中轮询至终态;终态展示产物 / 失败 error。
function JobDetail({ id, onClose }: { id: string; onClose: () => void }) {
  const [job, setJob] = useState<Job | null>(null)
  const [error, setError] = useState('')
  const [registering, setRegistering] = useState(false)
  const [registerErr, setRegisterErr] = useState('')
  const [registered, setRegistered] = useState(false)

  // 注册产物到目录(succeeded 作业):kind=processed、format=lance、location=lance_uri、
  // num_samples 取自 job.rows_written(只读自 job,UI 不可编辑,FR-010)。
  // 血缘 derived_from 取 job.source_dataset(真实来源 raw 数据集,US3-AC1/SC-003);
  // 旧 job 无 source_dataset 时兜底用产出名 job.dataset(不阻塞注册)。
  const registerProduct = (j: Job) => {
    setRegistering(true)
    setRegisterErr('')
    registerDataset({
      name: j.dataset,
      group_id: j.group_id,
      kind: 'processed',
      scope: 'private',
      format: 'lance',
      location: j.lance_uri ?? undefined,
      derived_from: j.source_dataset ?? j.dataset, // 真实来源(旧 job 无则兜底产出名)
      num_samples: j.rows_written ?? undefined, // 只读自 job(FR-010)
    })
      .then(() => setRegistered(true))
      .catch((e: unknown) => setRegisterErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setRegistering(false))
  }

  useEffect(() => {
    let alive = true
    // 先取一次详情;若非终态则继续轮询至终态。
    // (不在 effect 体内同步 setState——靠 key={id} 重挂得到干净初值,见调用处。)
    getJob(id)
      .then(j => {
        if (!alive) return
        setJob(j)
        if (!j.terminal) {
          pollJob(id)
            .then(final => { if (alive) setJob(final) })
            .catch((e: unknown) => { if (alive) setError(e instanceof Error ? e.message : String(e)) })
        }
      })
      .catch((e: unknown) => { if (alive) setError(e instanceof Error ? e.message : String(e)) })
    return () => { alive = false }
  }, [id])

  return (
    <div className="fixed inset-0 z-30 flex justify-end">
      <div className="absolute inset-0 bg-slate-900/30" onClick={onClose} />
      <div className="relative w-full max-w-md h-full bg-white shadow-xl overflow-auto">
        <div className="h-16 px-6 flex items-center border-b border-slate-100">
          <h2 className="font-semibold text-base">作业详情</h2>
          <button
            onClick={onClose}
            aria-label="关闭"
            className="ml-auto p-1.5 rounded-lg text-slate-400 hover:bg-slate-100"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18" /></svg>
          </button>
        </div>

        <div className="p-6">
          {error && <div className="text-red-500 text-sm">加载失败:{error}</div>}
          {!error && !job && <div className="text-slate-400 text-sm">加载中…</div>}
          {!error && job && (
            <div className="space-y-5 text-sm">
              <div className="flex items-center gap-3">
                <StatusBadge status={job.status} />
                {!job.terminal && <span className="text-xs text-slate-400">轮询中…</span>}
              </div>

              <dl className="grid grid-cols-[88px_1fr] gap-y-3">
                <dt className="text-slate-500">作业 ID</dt>
                <dd className="text-slate-700 break-all">{dash(job.id)}</dd>
                <dt className="text-slate-500">数据集</dt>
                <dd className="text-slate-700">{dash(job.dataset)}</dd>
                <dt className="text-slate-500">用户组</dt>
                <dd className="text-slate-700">{dash(job.group_id)}</dd>
                <dt className="text-slate-500">输入行数</dt>
                <dd className="text-slate-700">{fmtNum(job.rows_in)}</dd>
                <dt className="text-slate-500">写入行数</dt>
                <dd className="text-slate-700">{fmtNum(job.rows_written)}</dd>
                <dt className="text-slate-500">创建时间</dt>
                <dd className="text-slate-700">{fmtDate(job.created_at)}</dd>
              </dl>

              {/* 终态成功:展示产物 lance_uri + 注册产物到目录 */}
              {job.terminal && job.status === 'succeeded' && (
                <div>
                  <p className="text-slate-500 mb-1.5">产物(Lance URI)</p>
                  <code className="block bg-slate-50 border border-slate-200 rounded-lg px-3 py-2 text-xs text-slate-700 break-all">
                    {dash(job.lance_uri)}
                  </code>

                  {/* 注册产物:kind=processed、location=lance_uri、num_samples 只读自 job(FR-010) */}
                  <div className="mt-4">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-slate-500">样本数(取自作业,不可编辑)</span>
                      <span className="text-slate-700 font-medium">{fmtNum(job.rows_written)}</span>
                    </div>
                    {registered ? (
                      <p className="text-emerald-600 text-xs mt-2">已注册到目录。</p>
                    ) : (
                      <button
                        type="button"
                        onClick={() => registerProduct(job)}
                        disabled={registering || !job.lance_uri}
                        className="mt-2 text-white text-sm font-medium px-4 py-2 rounded-xl transition-colors disabled:opacity-50"
                        style={{ background: BRAND }}
                      >{registering ? '注册中…' : '注册产物'}</button>
                    )}
                    {registerErr && <p className="text-red-500 text-xs mt-2">注册失败:{registerErr}</p>}
                  </div>

                  {/* 二次处理:US3-AC3 v1 不提供 → 诚实占位(禁用态),不给会失败的按钮 */}
                  <div className="mt-4">
                    <button
                      type="button"
                      disabled
                      title="二次处理暂未提供(v-next)"
                      className="text-sm font-medium px-4 py-2 rounded-xl border border-slate-200 text-slate-400 cursor-not-allowed"
                    >再处理(暂未提供 · v-next)</button>
                  </div>
                </div>
              )}

              {/* 失败排障(US5):详情看 error */}
              {job.terminal && job.status === 'failed' && (
                <div>
                  <p className="text-red-600 font-medium mb-1.5 flex items-center gap-1.5">
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9" /><path d="M12 8v5M12 16h.01" /></svg>
                    失败原因
                  </p>
                  <pre className="bg-red-50 border border-red-200 rounded-lg px-3 py-2 text-xs text-red-700 whitespace-pre-wrap break-words">
                    {dash(job.error)}
                  </pre>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export function Pipelines() {
  const [jobs, setJobs] = useState<Job[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [filter, setFilter] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)

  // 注:加载逻辑用 Promise.then(setState) 回调形态(非 effect 内同步 setState),
  // 以满足 react-hooks/set-state-in-effect(参照 Datasets.tsx 的 fetch-on-mount 写法)。
  const load = useCallback((status: string) => {
    return listJobs(status || undefined)
      .then(res => { setJobs(res.jobs ?? []); setError('') })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { void load(filter) }, [load, filter])

  return (
    <div>
      <div className="flex items-center gap-2 mb-4">
        {FILTERS.map(f => (
          <button
            key={f.value}
            onClick={() => setFilter(f.value)}
            className={`text-sm font-medium px-3.5 py-2 rounded-xl transition-colors ${
              filter === f.value ? 'text-white' : 'text-slate-600 hover:bg-slate-100'
            }`}
            style={filter === f.value ? { background: BRAND } : undefined}
          >
            {f.label}
          </button>
        ))}
      </div>

      <div className="bg-white border border-slate-200/70 rounded-2xl overflow-hidden shadow-sm">
        <table className="w-full text-sm">
          <thead className="bg-slate-50/70 text-slate-500 text-xs">
            <tr className="text-left">
              <th className="font-medium px-5 py-3">作业 ID</th>
              <th className="font-medium px-5 py-3">数据集</th>
              <th className="font-medium px-5 py-3">状态</th>
              <th className="font-medium px-5 py-3">行数(出/入)</th>
              <th className="font-medium px-5 py-3">创建</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {loading && (
              <tr><td colSpan={5} className="px-5 py-8 text-center text-slate-400">加载中…</td></tr>
            )}
            {!loading && error && (
              <tr><td colSpan={5} className="px-5 py-8 text-center text-red-500">加载失败:{error}</td></tr>
            )}
            {!loading && !error && jobs.length === 0 && (
              <tr><td colSpan={5} className="px-5 py-8 text-center text-slate-400">暂无作业</td></tr>
            )}
            {!loading && !error && jobs.map(j => (
              <tr
                key={j.id}
                onClick={() => setSelectedId(j.id)}
                className="cursor-pointer hover:bg-slate-50"
              >
                <td className="px-5 py-3 font-medium text-[#4F46E5]">{j.id}</td>
                <td className="px-5 py-3 text-slate-600">{dash(j.dataset)}</td>
                <td className="px-5 py-3"><StatusBadge status={j.status} /></td>
                <td className="px-5 py-3 text-xs text-slate-600">
                  {fmtNum(j.rows_written)} / {fmtNum(j.rows_in)}
                </td>
                <td className="px-5 py-3 text-slate-500">{fmtDate(j.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {selectedId && <JobDetail key={selectedId} id={selectedId} onClose={() => setSelectedId(null)} />}
    </div>
  )
}
