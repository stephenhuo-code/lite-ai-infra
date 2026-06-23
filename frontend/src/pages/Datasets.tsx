import { useCallback, useEffect, useMemo, useState } from 'react'
// 注:加载逻辑用 Promise.then(setState) 回调形态(非 async/await 后同步 setState),
// 以满足 react-hooks/set-state-in-effect(参照 auth/useOrgs.ts 的 fetch-on-mount 写法)。
import { api } from '../api/client'
import type { components as MetaComp } from '../api/types-metadata'
import type { components as PipeComp } from '../api/types-datapipeline'
import { registerDataset } from '../api/datasets'
import { UploadModal } from './UploadModal'

// 数据集页(US1 列表 + 搜索 / US2 上传 / catalog-driven 注册 · ADR-023)。
// 列表 = metadata 数据集(GET /v1/catalogs/data/schemas/datasets/datasets,含 raw+processed、带 kind)
//        + pipeline 原始上传(GET /v1/data/raw,标「原始」)合并。
// 原始上传 ready 且尚未在 catalog → 显「注册到目录」(registerDataset kind=raw,无 location)。
// 列 = 名称/类型/格式/样本数/大小/创建人(owner)/操作。已处理项展示血缘(derived_from)。
// 创建人 = owner(上传/创建者,owner 模型 · ADR-024);缺失显「—」。
// 缺值显「—」不报错(FR-008)。禁出现 模态/标签/用户组 列(FR-012 + 组织模型)。
// 视觉照高保真原型 2026-06-22-data-domain-hifi.html 数据集页(靛蓝 #6366F1)。

type Dataset = MetaComp['schemas']['Dataset']
type RawDataset = PipeComp['schemas']['RawDataset']

// 合并后的统一行模型(字段名以生成类型为准)。
// 详情抽屉(US1 AC4)展示已有属性,故 Row 额外携带 location/scope/status/kind/derivedFrom。
// 注:不携带 e-/g- 内部 ID(FR-004)。归属真相源 = owner(创建人,ADR-024)。
type Row = {
  key: string
  name: string
  desc: string | null
  kind: string | null // catalog 项:raw|processed;原始上传项为 null(用 raw 标记)
  format: string | null // 原始上传项固定「原始」
  numSamples: number | null
  sizeBytes: number | null
  createdBy: string | null
  location: string | null
  scope: Dataset['scope'] | null
  derivedFrom: string | null // 已处理数据集的血缘来源
  status: RawDataset['status'] | null // 仅原始上传项有
  raw: boolean // true = 来自 /v1/data/raw 的上传项
  registerable: boolean // 原始上传项 ready 且尚未在 catalog → 可注册
}

// 纯转换:把两端响应合并成统一行模型(无 setState,便于在 .then 回调里调用)。
function toRows(
  meta: MetaComp['schemas']['DatasetList'],
  raw: PipeComp['schemas']['RawDatasetList'],
): Row[] {
  // 已在 catalog 的名字集合(用于判断原始上传项是否已注册)。
  const inCatalog = new Set((meta.datasets ?? []).map(d => d.name))
  const metaRows: Row[] = (meta.datasets ?? []).map((d: Dataset) => ({
    key: `meta:${d.name}`,
    name: d.name,
    desc: d.comment ?? null,
    kind: d.kind ?? null,
    format: d.format ?? null,
    numSamples: d.num_samples ?? null,
    sizeBytes: d.size_bytes ?? null,
    createdBy: d.created_by ?? d.owner ?? null,
    location: d.location ?? null,
    scope: d.scope ?? null,
    derivedFrom: d.derived_from ?? null,
    status: null,
    raw: false,
    registerable: false,
  }))
  const rawRows: Row[] = (raw.raw ?? []).map((r: RawDataset) => ({
    key: `raw:${r.id}`,
    name: r.name,
    desc: null,
    kind: null,
    format: '原始',
    numSamples: null,
    sizeBytes: r.size ?? null,
    createdBy: r.owner_user ?? null,
    location: null,
    scope: null,
    derivedFrom: null,
    status: r.status ?? null,
    raw: true,
    // ready 且尚未在 catalog → 可「注册到目录」(已在 catalog 的不再重复登记)。
    registerable: r.status === 'ready' && !inCatalog.has(r.name),
  }))
  return [...metaRows, ...rawRows]
}

// kind 中文映射(catalog 项):raw=原始、processed=已处理;缺值显「—」。
function kindLabel(kind: string | null, raw: boolean): string {
  if (raw) return '原始'
  if (kind === 'raw') return '原始'
  if (kind === 'processed') return '已处理'
  return '—'
}

function dash(v: string | number | null | undefined): string {
  return v === null || v === undefined || v === '' ? '—' : String(v)
}

function fmtBytes(b: number | null): string {
  if (b === null || b === undefined) return '—'
  if (b < 1024) return `${b} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let v = b / 1024
  let i = 0
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++ }
  return `${v.toFixed(1)} ${units[i]}`
}

function fmtNum(n: number | null): string {
  return n === null || n === undefined ? '—' : n.toLocaleString('en-US')
}

// 是否共享:scope 文案(私有/已共享),缺值显「—」。
function scopeLabel(s: Dataset['scope'] | null): string {
  if (s === 'shared') return '已共享'
  if (s === 'private') return '私有'
  return '—'
}

// 原始数据状态文案(就绪/处理中/失败),缺值显「—」。
function statusLabel(s: RawDataset['status'] | null): string {
  if (s === 'ready') return '就绪'
  if (s === 'pending') return '处理中'
  if (s === 'failed') return '失败'
  return '—'
}

// 数据集详情侧抽屉(US1 AC4):展示该数据集已有属性。
// 复用 Pipelines.tsx 的右侧抽屉模式。不显 e-/g- 内部 ID(FR-004)。
function DatasetDetail({ row, onClose }: { row: Row; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-30 flex justify-end">
      <div className="absolute inset-0 bg-slate-900/30" onClick={onClose} />
      <div className="relative w-full max-w-md h-full bg-white shadow-xl overflow-auto">
        <div className="h-16 px-6 flex items-center border-b border-slate-100">
          <h2 className="font-semibold text-base">数据集详情</h2>
          <button
            onClick={onClose}
            aria-label="关闭"
            className="ml-auto p-1.5 rounded-lg text-slate-400 hover:bg-slate-100"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18" /></svg>
          </button>
        </div>

        <div className="p-6">
          <div className="flex items-center gap-2 mb-5">
            <h3 className="font-semibold text-lg break-all">{row.name}</h3>
            {row.raw && <span className="text-[10px] font-normal text-slate-500 bg-slate-100 rounded px-1.5 py-0.5">原始</span>}
          </div>

          <dl className="grid grid-cols-[88px_1fr] gap-y-3 text-sm">
            <dt className="text-slate-500">描述</dt>
            <dd className="text-slate-700">{dash(row.desc)}</dd>
            <dt className="text-slate-500">类型</dt>
            <dd className="text-slate-700">{kindLabel(row.kind, row.raw)}</dd>
            <dt className="text-slate-500">格式</dt>
            <dd className="text-slate-700">{dash(row.format)}</dd>
            {/* 已处理数据集显血缘来源(derived_from) */}
            {row.kind === 'processed' && (
              <>
                <dt className="text-slate-500">来源</dt>
                <dd className="text-slate-700 break-all">{dash(row.derivedFrom)}</dd>
              </>
            )}
            <dt className="text-slate-500">样本数</dt>
            <dd className="text-slate-700">{fmtNum(row.numSamples)}</dd>
            <dt className="text-slate-500">大小</dt>
            <dd className="text-slate-700">{fmtBytes(row.sizeBytes)}</dd>
            <dt className="text-slate-500">创建人</dt>
            <dd className="text-slate-700">{dash(row.createdBy)}</dd>
            <dt className="text-slate-500">位置</dt>
            <dd className="text-slate-700 break-all">{dash(row.location)}</dd>
            <dt className="text-slate-500">是否共享</dt>
            <dd className="text-slate-700">{scopeLabel(row.scope)}</dd>
            {/* 原始上传项则显状态 */}
            {row.raw && (
              <>
                <dt className="text-slate-500">状态</dt>
                <dd className="text-slate-700">{statusLabel(row.status)}</dd>
              </>
            )}
          </dl>
        </div>
      </div>
    </div>
  )
}

export function Datasets() {
  const [rows, setRows] = useState<Row[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [q, setQ] = useState('')
  const [showUpload, setShowUpload] = useState(false)
  const [detailKey, setDetailKey] = useState<string | null>(null)
  const [registering, setRegistering] = useState<string | null>(null) // 正在注册的行 key

  const load = useCallback(() => {
    return Promise.all([
      api.get('/v1/catalogs/data/schemas/datasets/datasets') as Promise<MetaComp['schemas']['DatasetList']>,
      api.get('/v1/data/raw') as Promise<PipeComp['schemas']['RawDatasetList']>,
    ])
      .then(([meta, raw]) => setRows(toRows(meta, raw)))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { void load() }, [load])

  // 原始上传项「注册到目录」:registerDataset kind=raw,无 location(服务端钉死)。
  // 成功后刷新列表(注册后该项归入 catalog,不再显注册按钮)。
  const register = useCallback((row: Row) => {
    setRegistering(row.key)
    setError('')
    registerDataset({ name: row.name, kind: 'raw', scope: 'private' })
      .then(() => load())
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setRegistering(null))
  }, [load])

  const filtered = useMemo(() => {
    const term = q.trim().toLowerCase()
    if (!term) return rows
    return rows.filter(r => r.name.toLowerCase().includes(term))
  }, [rows, q])

  const detailRow = useMemo(
    () => rows.find(r => r.key === detailKey) ?? null,
    [rows, detailKey],
  )

  return (
    <div>
      <div className="flex items-center gap-3 mb-4">
        <button
          onClick={() => setShowUpload(true)}
          className="bg-[#6366F1] hover:bg-[#4F46E5] text-white text-sm font-medium px-4 py-2.5 rounded-xl flex items-center gap-2 transition-colors"
        >
          <svg className="w-[18px] h-[18px]" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path d="M12 16V4m0 0L8 8m4-4l4 4M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2" /></svg>
          上传数据集
        </button>
        <div className="ml-auto relative">
          <svg className="w-[18px] h-[18px] text-slate-400 absolute left-3 top-2.5" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><circle cx="11" cy="11" r="7" /><path d="M21 21l-4-4" /></svg>
          <input
            value={q}
            onChange={e => setQ(e.target.value)}
            placeholder="搜索数据集名称"
            aria-label="搜索数据集名称"
            className="w-64 rounded-xl border border-slate-300 pl-10 pr-3 py-2 text-sm focus:border-[#6366F1] outline-none"
          />
        </div>
      </div>

      <div className="bg-white border border-slate-200/70 rounded-2xl overflow-hidden shadow-sm">
        <table className="w-full text-sm">
          <thead className="bg-slate-50/70 text-slate-500 text-xs">
            <tr className="text-left">
              <th className="font-medium px-5 py-3">名称</th>
              <th className="font-medium px-5 py-3">类型</th>
              <th className="font-medium px-5 py-3">格式</th>
              <th className="font-medium px-5 py-3">样本数</th>
              <th className="font-medium px-5 py-3">大小</th>
              <th className="font-medium px-5 py-3">创建人</th>
              <th className="font-medium px-5 py-3">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {loading && (
              <tr><td colSpan={7} className="px-5 py-8 text-center text-slate-400">加载中…</td></tr>
            )}
            {!loading && error && (
              <tr><td colSpan={7} className="px-5 py-8 text-center text-red-500">加载失败:{error}</td></tr>
            )}
            {!loading && !error && filtered.length === 0 && (
              <tr><td colSpan={7} className="px-5 py-8 text-center text-slate-400">暂无数据集</td></tr>
            )}
            {!loading && !error && filtered.map(r => (
              <tr
                key={r.key}
                onClick={() => setDetailKey(r.key)}
                className="cursor-pointer hover:bg-slate-50"
              >
                <td className="px-5 py-3">
                  <div className="font-medium text-[#4F46E5] flex items-center gap-2">
                    {r.name}
                    {r.raw && <span className="text-[10px] font-normal text-slate-500 bg-slate-100 rounded px-1.5 py-0.5">原始</span>}
                  </div>
                </td>
                <td className="px-5 py-3 text-slate-500">{kindLabel(r.kind, r.raw)}</td>
                <td className="px-5 py-3 text-slate-500">{dash(r.format)}</td>
                <td className="px-5 py-3 text-xs text-slate-600">{fmtNum(r.numSamples)}</td>
                <td className="px-5 py-3 text-slate-500">{fmtBytes(r.sizeBytes)}</td>
                <td className="px-5 py-3 text-slate-600">{dash(r.createdBy)}</td>
                <td className="px-5 py-3">
                  <div className="flex items-center gap-3">
                    {/* 原始上传项 ready 且未在 catalog → 注册到目录(kind=raw,无 location) */}
                    {r.registerable && (
                      <button
                        onClick={e => { e.stopPropagation(); register(r) }}
                        disabled={registering === r.key}
                        className="text-xs text-emerald-700 hover:underline disabled:opacity-50"
                      >{registering === r.key ? '注册中…' : '注册到目录'}</button>
                    )}
                    <button
                      onClick={e => { e.stopPropagation(); setDetailKey(r.key) }}
                      className="text-xs text-[#4F46E5] hover:underline"
                    >详情</button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {showUpload && (
        <UploadModal
          onClose={() => setShowUpload(false)}
          onDone={() => { setLoading(true); setError(''); void load() }}
        />
      )}

      {detailRow && (
        <DatasetDetail row={detailRow} onClose={() => setDetailKey(null)} />
      )}
    </div>
  )
}
