import { useState } from 'react'
import { createAgent, updateAgent, type LibraryAgent } from '../api/omnigent'

// 新建/编辑智能体弹窗(智能体库 / US2 · ADR-027)。仅企业管理员可见入口;服务端 can() 兜底。
// 字段:名字(必填)+ 系统提示词(可选)+ 模型(可选)+ harness(基底)。
// harness ∈ claude-native(默认)| claude-sdk | codex | qwen | pi。
// 凭据不再随 agent 走 —— 模型凭据由企业管理员在「模型配置」页统一配(ADR-028),
// 按 harness 的 provider 自动注入本企业沙箱。故此弹窗无 API Key/Base URL 字段。
//
// 双模:create | edit。edit 仅能预填 name + harness(BFF 列表不回传其余字段),
// 故 edit 为破坏性覆盖 —— 留空的提示词/模型会被清除,需醒目告警。
// 视觉照 UploadModal(靛蓝 #6366F1)。

const HARNESSES = [
  { value: 'claude-native', label: 'claude-native(默认)', hint: 'Anthropic 原生基底。模型凭据在「模型配置」页统一管理。' },
  { value: 'claude-sdk', label: 'claude-sdk', hint: '通过 Anthropic SDK 调用。模型凭据在「模型配置」页统一管理。' },
  { value: 'openai-agents', label: 'openai-agents(OpenAI 兼容)', hint: 'OpenAI 及兼容 provider(MiniMax / DeepSeek / vLLM 等):在「模型配置」把 OpenAI 配成 API key + base_url,并在下方【模型】填该 provider 的模型名(如 MiniMax-Text-01)。' },
  { value: 'codex', label: 'codex(ChatGPT 订阅)', hint: 'OpenAI Codex 原生基底。仅认 ChatGPT 订阅登录,不吃 API key;要用 API key 接 OpenAI 兼容 provider 请选 openai-agents。' },
  { value: 'qwen', label: 'qwen', hint: '通义千问基底。模型凭据在「模型配置」页统一管理。' },
  { value: 'pi', label: 'pi', hint: 'Pi 基底。模型凭据在「模型配置」页统一管理。' },
] as const

// 需要显式填模型名的 harness(多模型基底:openai-agents 接兼容 provider 时模型名必填,否则 model=None 会失败)。
const MODEL_REQUIRED_HARNESSES = new Set(['openai-agents'])

type Props = {
  onClose: () => void
  onDone: () => void // 成功后由父刷新列表
  mode?: 'create' | 'edit'
  agent?: LibraryAgent // edit 模式必传:提供 id + 预填 name/harness
}

type Phase = 'idle' | 'submitting' | 'error'

// BFF 4xx 状态 → 可理解中文提示(不裸露 HTTP 码;失败显式不静默)。
function errMessage(e: unknown, mode: 'create' | 'edit'): string {
  const msg = e instanceof Error ? e.message : String(e)
  const verb = mode === 'edit' ? '保存' : '创建'
  if (msg === '403') return `你没有${verb === '保存' ? '编辑' : '创建'}智能体的权限(需企业管理员)。`
  if (msg === '400') return `${verb}失败:字段无效(名字 / 基底配置),请检查后再试。`
  if (msg === '409') return `${verb}失败:同企业内已存在同名智能体。`
  return `${verb}失败:${msg}`
}

export function CreateAgentModal({ onClose, onDone, mode = 'create', agent }: Props) {
  const isEdit = mode === 'edit'
  const [name, setName] = useState(isEdit ? (agent?.name ?? '') : '')
  const [instructions, setInstructions] = useState('')
  const [model, setModel] = useState('')
  const [harness, setHarness] = useState(isEdit ? (agent?.harness ?? 'claude-native') : 'claude-native')
  const [phase, setPhase] = useState<Phase>('idle')
  const [err, setErr] = useState('')

  const modelRequired = MODEL_REQUIRED_HARNESSES.has(harness)
  const canSubmit = name.trim() !== '' && phase !== 'submitting' && (!modelRequired || model.trim() !== '')

  async function submit() {
    if (name.trim() === '') { setErr('请填写名字。'); setPhase('error'); return }
    if (modelRequired && model.trim() === '') {
      setErr('该基底(openai-agents)需在【模型】填目标 provider 的模型名(如 MiniMax-Text-01),否则无法调用。')
      setPhase('error'); return
    }
    setPhase('submitting')
    setErr('')
    const input = { name, instructions, model, harness }
    try {
      if (isEdit && agent) await updateAgent(agent.id, input)
      else await createAgent(input)
      onDone() // 刷新列表 + 关弹窗(由父决定)
    } catch (e) {
      setErr(errMessage(e, mode))
      setPhase('error')
    }
  }

  return (
    <div className="fixed inset-0 z-40 grid place-items-center px-4">
      <div
        className="absolute inset-0 bg-slate-900/30 backdrop-blur-[2px]"
        onClick={onClose}
      />
      <div className="relative bg-white w-full max-w-lg rounded-2xl shadow-xl border border-slate-200 p-6 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-5">
          <h2 className="font-semibold text-lg">{isEdit ? '编辑智能体' : '新建智能体'}</h2>
          <button
            onClick={onClose}
            aria-label="关闭"
            className="text-slate-400 hover:text-slate-700"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path d="M18 6L6 18M6 6l12 12" /></svg>
          </button>
        </div>

        {/* edit 破坏性覆盖告警(BFF 用提交字段整体重建 bundle,留空字段被清) */}
        {isEdit && (
          <div className="mb-5 text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded-xl px-3.5 py-3">
            编辑会用下面填写的内容<strong>整体覆盖</strong>该智能体。
            <strong>留空的提示词 / 模型将被清除</strong>——要保留请重新填写。
          </div>
        )}

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
          <label className="block text-xs font-medium text-slate-600 mb-1.5" htmlFor="ag-model">模型{modelRequired ? ' *' : '(可选)'}</label>
          <input
            id="ag-model"
            value={model}
            onChange={e => { setModel(e.target.value); if (phase === 'error') { setErr(''); setPhase('idle') } }}
            placeholder={modelRequired ? '如 MiniMax-Text-01(该 provider 的模型名)' : '留空用模板默认模型'}
            className="w-full rounded-xl border border-slate-300 px-3.5 py-2.5 text-sm focus:border-[#6366F1] outline-none"
          />
          {modelRequired && (
            <p className="text-[11px] text-slate-400 mt-1.5">openai-agents 需指定模型名;可在 provider 文档或其 /v1/models 查看可用模型。</p>
          )}
        </div>

        {/* harness 选择:凭据统一走「模型配置」,此处不再填 key */}
        <div className="mb-4">
          <label className="block text-xs font-medium text-slate-600 mb-1.5" htmlFor="ag-harness">基底(harness)</label>
          <select
            id="ag-harness"
            value={harness}
            onChange={e => { setHarness(e.target.value); if (phase === 'error') { setErr(''); setPhase('idle') } }}
            aria-label="基底 harness"
            className="w-full rounded-xl border border-slate-300 px-3.5 py-2.5 text-sm focus:border-[#6366F1] outline-none bg-white"
          >
            {HARNESSES.map(h => <option key={h.value} value={h.value}>{h.label}</option>)}
          </select>
          <p className="text-[11px] text-slate-400 mt-1.5">{HARNESSES.find(h => h.value === harness)?.hint}</p>
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
            {phase === 'submitting'
              ? (isEdit ? '保存中…' : '创建中…')
              : phase === 'error'
                ? '重试'
                : (isEdit ? '保存' : '创建')}
          </button>
        </div>
      </div>
    </div>
  )
}
