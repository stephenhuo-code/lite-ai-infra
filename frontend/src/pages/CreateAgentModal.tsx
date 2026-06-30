import { useState } from 'react'
import { createAgent, updateAgent, type LibraryAgent } from '../api/omnigent'

// 新建/编辑智能体弹窗(智能体库 / US2 · ADR-027)。仅企业管理员可见入口;服务端 can() 兜底。
// 字段:名字(必填)+ 系统提示词(可选)+ 模型(可选)+ harness(基底)。
// harness ∈ claude-native(默认,平台全局订阅,无需 key)| claude-sdk | codex | qwen | pi
// (后四个为 SDK harness,需自带 api_key + 可选 base_url)。
// 服务端门:SDK harness 缺 key → 400;claude-native 带 key → 400;key 含 ${}/$VAR → 400。
// 本弹窗在客户端先行校验,避免用户撞裸 400。
//
// 双模:create | edit。edit 仅能预填 name + harness(BFF 列表不回传其余字段),
// 故 edit 为破坏性覆盖 —— 留空的提示词/模型/key 会被清除,需醒目告警。
// 视觉照 UploadModal(靛蓝 #6366F1)。

const HARNESSES = [
  { value: 'claude-native', label: 'claude-native(默认)', hint: '平台已注入全局共享订阅,无需你自己的 API key。', needsKey: false },
  { value: 'claude-sdk', label: 'claude-sdk', hint: '通过 Anthropic SDK 调用,需你自己的 API key。', needsKey: true },
  { value: 'codex', label: 'codex', hint: 'OpenAI Codex 基底,需你自己的 API key。', needsKey: true },
  { value: 'qwen', label: 'qwen', hint: '通义千问基底,需你自己的 API key。', needsKey: true },
  { value: 'pi', label: 'pi', hint: 'Pi 基底,需你自己的 API key。', needsKey: true },
] as const

function needsKey(harness: string): boolean {
  return HARNESSES.find(h => h.value === harness)?.needsKey ?? false
}

// 形似变量引用的 key(${FOO} 或 $FOO)——服务端会 400 拒。前端先拦,给友好提示。
function looksLikeVarRef(key: string): boolean {
  return /\$\{|\$[A-Za-z_]/.test(key)
}

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
  if (msg === '400') return `${verb}失败:字段无效(名字 / API key / 基底配置),请检查后再试。`
  if (msg === '409') return `${verb}失败:同企业内已存在同名智能体。`
  return `${verb}失败:${msg}`
}

export function CreateAgentModal({ onClose, onDone, mode = 'create', agent }: Props) {
  const isEdit = mode === 'edit'
  const [name, setName] = useState(isEdit ? (agent?.name ?? '') : '')
  const [instructions, setInstructions] = useState('')
  const [model, setModel] = useState('')
  const [harness, setHarness] = useState(isEdit ? (agent?.harness ?? 'claude-native') : 'claude-native')
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [phase, setPhase] = useState<Phase>('idle')
  const [err, setErr] = useState('')

  const showCreds = needsKey(harness)
  const canSubmit = name.trim() !== '' && phase !== 'submitting'

  // 客户端前置校验:返回错误文案(null = 通过)。镜像服务端门。
  function validate(): string | null {
    if (name.trim() === '') return '请填写名字。'
    if (needsKey(harness)) {
      if (apiKey.trim() === '') return `该 harness(${harness})需要你自己的 API key,请填写。`
      if (looksLikeVarRef(apiKey)) return 'API key 不能是 ${VAR} / $VAR 形式的变量引用,请填入真实的密钥值。'
    }
    return null
  }

  async function submit() {
    const v = validate()
    if (v) { setErr(v); setPhase('error'); return }
    setPhase('submitting')
    setErr('')
    // claude-native 不下发 key(服务端会 400);SDK harness 才带 key/base_url。
    const input = {
      name,
      instructions,
      model,
      harness,
      ...(showCreds ? { api_key: apiKey, base_url: baseUrl } : {}),
    }
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
            <strong>留空的提示词 / 模型 / API Key 将被清除</strong>——要保留请重新填写。
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
          <label className="block text-xs font-medium text-slate-600 mb-1.5" htmlFor="ag-model">模型(可选)</label>
          <input
            id="ag-model"
            value={model}
            onChange={e => setModel(e.target.value)}
            placeholder="留空用模板默认模型"
            className="w-full rounded-xl border border-slate-300 px-3.5 py-2.5 text-sm focus:border-[#6366F1] outline-none"
          />
        </div>

        {/* harness 选择:claude-native 默认无需 key;其余 SDK harness 需自带 key */}
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

        {/* 条件凭据字段:仅 SDK harness 显示。key 用 password 型;base_url 可选 */}
        {showCreds && (
          <>
            <div className="mb-4">
              <label className="block text-xs font-medium text-slate-600 mb-1.5" htmlFor="ag-api-key">API Key *</label>
              <input
                id="ag-api-key"
                type="password"
                value={apiKey}
                onChange={e => setApiKey(e.target.value)}
                placeholder="sk-..."
                autoComplete="off"
                className="w-full rounded-xl border border-slate-300 px-3.5 py-2.5 text-sm focus:border-[#6366F1] outline-none"
              />
              <p className="text-[11px] text-slate-400 mt-1.5">该 harness 需要你自己的 API key{isEdit ? '(留空将清除已存的 key)' : ''}</p>
            </div>
            <div className="mb-4">
              <label className="block text-xs font-medium text-slate-600 mb-1.5" htmlFor="ag-base-url">Base URL(可选)</label>
              <input
                id="ag-base-url"
                value={baseUrl}
                onChange={e => setBaseUrl(e.target.value)}
                placeholder="留空用该 harness 默认 endpoint"
                className="w-full rounded-xl border border-slate-300 px-3.5 py-2.5 text-sm focus:border-[#6366F1] outline-none"
              />
            </div>
          </>
        )}

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
