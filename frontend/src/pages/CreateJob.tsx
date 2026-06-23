import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { createJob } from '../api/jobs'
import type { PrepareJobRequest } from '../api/jobs'
import { listDatasets } from '../api/datasets'
import type { Dataset } from '../api/datasets'

// 创建作业页(US4 提交)。
// 源 = 已注册的 raw 数据集(catalog-driven · ADR-023):挂载拉 listDatasets()→
// 过滤 kind==='raw'→ 下拉选 source_dataset;提交 source_dataset(不再传 tar_dir)。
// 表单:源数据集(下拉) + 产出数据集名 + group_id + 并行度(np) + 算子(可选 chips)。
// → createJob → 202 提示 → 跳 /pipelines。
// 视觉照高保真原型 2026-06-22-data-domain-hifi.html 创建作业段(靛蓝 #6366F1)。

const BRAND = '#6366F1'
const BRAND_DARK = '#4F46E5'

// 可选算子 chips(S1 预置常见清洗算子;process 透传给契约)。
const OPERATORS = ['去重', '语言过滤', '低质过滤', 'PII 脱敏', '分词']

export function CreateJob() {
  const navigate = useNavigate()
  const [source, setSource] = useState('')
  const [sources, setSources] = useState<Dataset[]>([])
  const [dataset, setDataset] = useState('')
  const [groupId, setGroupId] = useState('')
  const [np, setNp] = useState('')
  const [ops, setOps] = useState<string[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  // 挂载拉数据集列表,过滤 kind==='raw' 作为可选源(catalog-driven · ADR-023)。
  // 用 .then(setState) 回调形态(非 effect 内同步 setState),对齐 Datasets/Pipelines 写法。
  useEffect(() => {
    listDatasets()
      .then(res => setSources((res.datasets ?? []).filter(d => d.kind === 'raw')))
      .catch(() => setSources([]))
  }, [])

  const toggleOp = (op: string) =>
    setOps(prev => (prev.includes(op) ? prev.filter(o => o !== op) : [...prev, op]))

  const canSubmit = source.trim() && dataset.trim() && groupId.trim() && !submitting

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!canSubmit) return
    setSubmitting(true)
    setError('')
    setNotice('')
    // 算子透传给契约 process(契约定义为开放对象数组;此处装为 {name} 对象)。
    const process = ops.length
      ? (ops.map(name => ({ name })) as unknown as PrepareJobRequest['process'])
      : undefined
    createJob({
      dataset: dataset.trim(),
      group_id: groupId.trim(),
      source_dataset: source,
      np: np.trim() ? Number(np) : undefined,
      process,
    })
      .then(() => {
        setNotice('作业已提交(202),正在跳转…')
        navigate('/pipelines')
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : String(err))
        setSubmitting(false)
      })
  }

  const inputCls =
    'w-full rounded-xl border border-slate-300 px-3.5 py-2.5 text-sm focus:border-[#6366F1] outline-none'

  return (
    <div className="max-w-2xl">
      <form onSubmit={submit} className="bg-white border border-slate-200/70 rounded-2xl p-6 shadow-sm space-y-5">
        {/* 源 = 已注册的 raw 数据集(catalog-driven · ADR-023)——只列 kind=raw */}
        <div>
          <label htmlFor="source_dataset" className="block text-sm font-medium text-slate-700 mb-1.5">
            源数据集
          </label>
          <select
            id="source_dataset"
            value={source}
            onChange={e => setSource(e.target.value)}
            className={inputCls}
          >
            <option value="">请选择源数据集…</option>
            {sources.map(d => (
              <option key={d.name} value={d.name}>{d.name}</option>
            ))}
          </select>
          <p className="text-xs text-slate-400 mt-1">仅列出已注册到目录的原始(raw)数据集。</p>
        </div>

        <div>
          <label htmlFor="dataset" className="block text-sm font-medium text-slate-700 mb-1.5">
            产出数据集名
          </label>
          <input
            id="dataset"
            value={dataset}
            onChange={e => setDataset(e.target.value)}
            placeholder="例:cc3m-clean"
            className={inputCls}
          />
        </div>

        <div>
          <label htmlFor="group_id" className="block text-sm font-medium text-slate-700 mb-1.5">
            用户组(group_id)
          </label>
          <input
            id="group_id"
            value={groupId}
            onChange={e => setGroupId(e.target.value)}
            placeholder="例:g-research"
            className={inputCls}
          />
        </div>

        <div>
          <label htmlFor="np" className="block text-sm font-medium text-slate-700 mb-1.5">
            并行度(np,可选)
          </label>
          <input
            id="np"
            type="number"
            min="1"
            value={np}
            onChange={e => setNp(e.target.value)}
            placeholder="例:8"
            className={inputCls}
          />
        </div>

        <div>
          <span className="block text-sm font-medium text-slate-700 mb-2">算子(可选)</span>
          <div className="flex flex-wrap gap-2">
            {OPERATORS.map(op => {
              const on = ops.includes(op)
              return (
                <button
                  key={op}
                  type="button"
                  onClick={() => toggleOp(op)}
                  aria-pressed={on}
                  className={`text-sm px-3 py-1.5 rounded-full border transition-colors ${
                    on ? 'text-white border-transparent' : 'text-slate-600 border-slate-300 hover:bg-slate-50'
                  }`}
                  style={on ? { background: BRAND } : undefined}
                >
                  {op}
                </button>
              )
            })}
          </div>
        </div>

        {error && <div className="text-red-500 text-sm">提交失败:{error}</div>}
        {notice && <div className="text-emerald-600 text-sm">{notice}</div>}

        <div className="flex items-center gap-3 pt-1">
          <button
            type="submit"
            disabled={!canSubmit}
            className="text-white text-sm font-medium px-4 py-2.5 rounded-xl transition-colors disabled:opacity-50"
            style={{ background: canSubmit ? BRAND : BRAND_DARK }}
          >
            {submitting ? '提交中…' : '提交作业'}
          </button>
          <button
            type="button"
            onClick={() => navigate('/pipelines')}
            className="text-sm text-slate-600 hover:bg-slate-50 px-4 py-2.5 rounded-xl"
          >
            取消
          </button>
        </div>
      </form>
    </div>
  )
}
