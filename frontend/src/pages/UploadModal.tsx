import { useRef, useState } from 'react'
import { uploadDataset } from '../api/upload'

// 上传弹窗(US2 / FR-010~011):表单 = 数据集名 + 选文件,**不选组**
// (组由身份带出,ADR-020)。提交走 uploadDataset 三段直传 + 进度条;
// 失败可重试;成功关弹窗 + 刷新列表。
// 视觉照高保真原型 2026-06-22-data-domain-hifi.html 上传弹窗(靛蓝 #6366F1)。

type Props = {
  onClose: () => void
  onDone: () => void // 成功后由父刷新列表
}

type Phase = 'idle' | 'uploading' | 'done' | 'error'

export function UploadModal({ onClose, onDone }: Props) {
  const [dataset, setDataset] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [pct, setPct] = useState(0)
  const [phase, setPhase] = useState<Phase>('idle')
  const [err, setErr] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  const canSubmit = dataset.trim() !== '' && file !== null && phase !== 'uploading'

  async function submit() {
    if (!file || dataset.trim() === '') return
    setPhase('uploading')
    setErr('')
    setPct(0)
    try {
      await uploadDataset(
        { dataset: dataset.trim(), filename: file.name, file },
        setPct,
      )
      setPhase('done')
      onDone() // 刷新列表
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
      setPhase('error')
    }
  }

  return (
    <div className="fixed inset-0 z-40 grid place-items-center px-4">
      <div
        className="absolute inset-0 bg-slate-900/30 backdrop-blur-[2px]"
        onClick={onClose}
      />
      <div className="relative bg-white w-full max-w-lg rounded-2xl shadow-xl border border-slate-200 p-6">
        <div className="flex items-center justify-between mb-5">
          <h2 className="font-semibold text-lg">上传数据集</h2>
          <button
            onClick={onClose}
            aria-label="关闭"
            className="text-slate-400 hover:text-slate-700"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path d="M18 6L6 18M6 6l12 12" /></svg>
          </button>
        </div>

        <div className="mb-4">
          <label className="block text-xs font-medium text-slate-600 mb-1.5" htmlFor="up-name">数据集名</label>
          <input
            id="up-name"
            value={dataset}
            onChange={e => setDataset(e.target.value)}
            placeholder="如 cc3m"
            className="w-full rounded-xl border border-slate-300 px-3.5 py-2.5 text-sm focus:border-[#6366F1] outline-none"
          />
          <p className="text-[11px] text-slate-400 mt-1.5">归属你 · 上传后出现在数据集列表,可用于创建作业</p>
        </div>

        {/* 选文件(不选组——组由身份带出) */}
        <input
          ref={fileRef}
          type="file"
          aria-label="选择文件"
          className="sr-only"
          onChange={e => setFile(e.target.files?.[0] ?? null)}
        />
        <button
          type="button"
          onClick={() => fileRef.current?.click()}
          className="w-full border-2 border-dashed border-slate-300 rounded-2xl py-10 grid place-items-center text-center hover:border-[#6366F1] hover:bg-[#EEF0FF]/50 transition-colors"
        >
          <svg className="w-12 h-12 text-slate-300 mb-2.5" fill="none" stroke="currentColor" strokeWidth="1.5" viewBox="0 0 24 24"><path d="M12 16V6m0 0L8 10m4-4l4 4" /><path d="M20 16.5A4.5 4.5 0 0016 8a6 6 0 00-11.6 1.5A4 4 0 005 17" /></svg>
          {file
            ? <p className="text-sm font-medium text-slate-700">{file.name}</p>
            : <p className="text-sm font-medium text-slate-700">点击选择文件</p>}
          <p className="text-xs text-slate-400 mt-1.5">支持单文件直传对象存储</p>
        </button>

        {(phase === 'uploading' || phase === 'done' || phase === 'error') && (
          <div className="mt-4">
            <div className="flex items-center justify-between text-sm mb-2">
              <span className="font-medium text-slate-700">{file?.name}</span>
              <span className="text-slate-500">{pct}%</span>
            </div>
            <div className="h-2 rounded-full bg-slate-100 overflow-hidden">
              <div
                className="h-full bg-[#6366F1] transition-all duration-200"
                style={{ width: `${pct}%` }}
              />
            </div>
            <ol className="grid grid-cols-3 gap-2 mt-3.5 text-xs text-slate-400">
              <li>1 申请通行证</li>
              <li>2 直传 OSS</li>
              <li>3 完成校验</li>
            </ol>
          </div>
        )}

        {phase === 'done' && (
          <div className="mt-3.5 flex items-center gap-2 text-sm text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-xl px-3.5 py-2.5">
            <svg className="w-[18px] h-[18px]" fill="none" stroke="currentColor" strokeWidth="2.2" viewBox="0 0 24 24"><path d="M20 6L9 17l-5-5" /></svg>
            上传完成,可在「创建作业」选为源。
          </div>
        )}

        {phase === 'error' && (
          <div className="mt-3.5 text-sm text-red-700 bg-red-50 border border-red-200 rounded-xl px-3.5 py-2.5">
            上传失败:{err}
          </div>
        )}

        <div className="flex justify-end gap-2 mt-6">
          <button
            onClick={onClose}
            className="text-sm text-slate-600 px-4 py-2.5 rounded-xl hover:bg-slate-100"
          >
            关闭
          </button>
          {phase === 'done'
            ? (
              <button
                onClick={onClose}
                className="text-sm font-medium text-white bg-[#6366F1] hover:bg-[#4F46E5] px-4 py-2.5 rounded-xl"
              >
                完成
              </button>
            )
            : (
              <button
                onClick={submit}
                disabled={!canSubmit}
                className="text-sm font-medium text-white bg-[#6366F1] hover:bg-[#4F46E5] px-4 py-2.5 rounded-xl disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {phase === 'uploading' ? '上传中…' : phase === 'error' ? '重试' : '上传'}
              </button>
            )}
        </div>
      </div>
    </div>
  )
}
