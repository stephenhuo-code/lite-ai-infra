import { useState } from 'react'
import { createAgent } from '../api/omnigent'

// 新建智能体弹窗(智能体库 / US2 · ADR-027)。仅企业管理员可见入口;服务端 can() 兜底。
// 9a 字段:名字(必填)+ 系统提示词(可选)+ 模型(可选);harness 固定 claude-native
// (唯一注入全局共享订阅的 harness;不提供 codex/其它——建出来不可用)。
// 无 MCP/工具/数据/per-agent 凭据(那是 9b)。提交成功后由父刷新列表。
// 视觉照 UploadModal(靛蓝 #6366F1)。

type Props = {
  onClose: () => void
  onDone: () => void // 成功后由父刷新列表
}

type Phase = 'idle' | 'submitting' | 'error'

// BFF 4xx 状态 → 可理解中文提示(不裸露 HTTP 码;失败显式不静默)。
function errMessage(e: unknown): string {
  const msg = e instanceof Error ? e.message : String(e)
  if (msg === '403') return '你没有创建智能体的权限(需企业管理员)。'
  if (msg === '400') return '创建失败:名字无效或重名,请换一个再试。'
  if (msg === '409') return '创建失败:同企业内已存在同名智能体。'
  return `创建失败:${msg}`
}

export function CreateAgentModal({ onClose, onDone }: Props) {
  const [name, setName] = useState('')
  const [instructions, setInstructions] = useState('')
  const [model, setModel] = useState('')
  const [phase, setPhase] = useState<Phase>('idle')
  const [err, setErr] = useState('')

  const canSubmit = name.trim() !== '' && phase !== 'submitting'

  async function submit() {
    if (name.trim() === '') return
    setPhase('submitting')
    setErr('')
    try {
      await createAgent({ name, instructions, model }) // harness 默认 claude-native
      onDone() // 刷新列表 + 关弹窗(由父决定)
    } catch (e) {
      setErr(errMessage(e))
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
          <h2 className="font-semibold text-lg">新建智能体</h2>
          <button
            onClick={onClose}
            aria-label="关闭"
            className="text-slate-400 hover:text-slate-700"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path d="M18 6L6 18M6 6l12 12" /></svg>
          </button>
        </div>

        <div className="mb-4">
          <label className="block text-xs font-medium text-slate-600 mb-1.5" htmlFor="ag-name">名字 *</label>
          <input
            id="ag-name"
            value={name}
            onChange={e => setName(e.target.value)}
            placeholder="如 客服助手"
            className="w-full rounded-xl border border-slate-300 px-3.5 py-2.5 text-sm focus:border-[#6366F1] outline-none"
          />
          <p className="text-[11px] text-slate-400 mt-1.5">归属本企业 · 创建后出现在智能体库,可用于建会话</p>
        </div>

        <div className="mb-4">
          <label className="block text-xs font-medium text-slate-600 mb-1.5" htmlFor="ag-instructions">系统提示词(可选)</label>
          <textarea
            id="ag-instructions"
            value={instructions}
            onChange={e => setInstructions(e.target.value)}
            rows={5}
            placeholder="如 你是一名耐心的客服助手,只回答与产品相关的问题。"
            className="w-full rounded-xl border border-slate-300 px-3.5 py-2.5 text-sm focus:border-[#6366F1] outline-none resize-y"
          />
          <p className="text-[11px] text-slate-400 mt-1.5">留空则用所选模板的默认设定</p>
        </div>

        <div className="mb-4">
          <label className="block text-xs font-medium text-slate-600 mb-1.5" htmlFor="ag-model">模型(可选)</label>
          <input
            id="ag-model"
            value={model}
            onChange={e => setModel(e.target.value)}
            placeholder="留空用模板默认模型"
            className="w-full rounded-xl border border-slate-300 px-3.5 py-2.5 text-sm focus:border-[#6366F1] outline-none"
          />
        </div>

        {/* harness 固定 claude-native(唯一注入全局订阅的);展示但禁用,不提供其它选项 */}
        <div className="mb-2">
          <label className="block text-xs font-medium text-slate-600 mb-1.5" htmlFor="ag-harness">基底(harness)</label>
          <input
            id="ag-harness"
            value="claude-native"
            disabled
            aria-label="基底 harness"
            className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3.5 py-2.5 text-sm text-slate-500"
          />
          <p className="text-[11px] text-slate-400 mt-1.5">当前仅支持 claude-native(平台已注入全局共享订阅)</p>
        </div>

        {phase === 'error' && (
          <div className="mt-3.5 text-sm text-red-700 bg-red-50 border border-red-200 rounded-xl px-3.5 py-2.5">
            {err}
          </div>
        )}

        <div className="flex justify-end gap-2 mt-6">
          <button
            onClick={onClose}
            className="text-sm text-slate-600 px-4 py-2.5 rounded-xl hover:bg-slate-100"
          >
            取消
          </button>
          <button
            onClick={submit}
            disabled={!canSubmit}
            className="text-sm font-medium text-white bg-[#6366F1] hover:bg-[#4F46E5] px-4 py-2.5 rounded-xl disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {phase === 'submitting' ? '创建中…' : phase === 'error' ? '重试' : '创建'}
          </button>
        </div>
      </div>
    </div>
  )
}
