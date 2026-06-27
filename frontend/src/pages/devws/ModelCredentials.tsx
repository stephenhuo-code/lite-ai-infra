import { useEffect, useState } from 'react'
import {
  fetchModelCredentials, putModelCredential, deleteModelCredential,
  type ModelProvider, type ModelCredentialStatus,
} from '../../api/devws'

// 订阅凭据 onboarding 设置页(Dev Workspace · T5)。每个 provider:连接状态 + 文本域粘贴凭据 +
// 「连接」(PUT)/「断开」(DELETE)。secret 只上行、永不回显;状态仅布尔。视觉照壳子(brand #6366F1)。
const BRAND = '#6366F1'

const PROVIDERS: { id: ModelProvider; label: string; hint: string }[] = [
  { id: 'claude', label: 'Claude', hint: '粘贴 `claude setup-token` 的输出' },
  { id: 'codex', label: 'Codex', hint: '粘贴 codex 的 auth.json 内容' },
]

export function ModelCredentials() {
  const [status, setStatus] = useState<ModelCredentialStatus>({ claude: false, codex: false })
  const [drafts, setDrafts] = useState<Record<ModelProvider, string>>({ claude: '', codex: '' })
  const [busy, setBusy] = useState<ModelProvider | null>(null)
  const [error, setError] = useState('')

  async function refresh() {
    try { setStatus(await fetchModelCredentials()) }
    catch { setError('无法加载订阅凭据状态') }
  }
  useEffect(() => {
    let alive = true
    fetchModelCredentials()
      .then(s => { if (alive) setStatus(s) })
      .catch(() => { if (alive) setError('无法加载订阅凭据状态') })
    return () => { alive = false }
  }, [])

  async function connect(p: ModelProvider) {
    const secret = drafts[p].trim()
    if (!secret) return
    setBusy(p); setError('')
    try {
      await putModelCredential(p, secret)
      setDrafts(d => ({ ...d, [p]: '' }))   // 连接后清空草稿,明文不留前端
      await refresh()
    } catch { setError(`连接 ${p} 失败`) }
    finally { setBusy(null) }
  }

  async function disconnect(p: ModelProvider) {
    setBusy(p); setError('')
    try { await deleteModelCredential(p); await refresh() }
    catch { setError(`断开 ${p} 失败`) }
    finally { setBusy(null) }
  }

  return (
    <div className="max-w-2xl mx-auto px-6 py-8 space-y-6">
      <div>
        <h1 className="text-lg font-semibold text-slate-800">订阅凭据</h1>
        <p className="text-sm text-slate-500 mt-1">
          连接你自己的 Claude / Codex 订阅。凭据加密存储,仅用于在你的工作区容器内运行 agent;界面不会回显明文。
        </p>
      </div>
      {error && <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">{error}</div>}
      {PROVIDERS.map(p => {
        const connected = status[p.id]
        return (
          <div key={p.id} className="border border-slate-200 rounded-2xl bg-white p-5 space-y-3">
            <div className="flex items-center gap-2">
              <span className="font-medium text-slate-800">{p.label}</span>
              {connected
                ? <span data-testid={`badge-${p.id}`} className="text-xs text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-full px-2 py-0.5">已连接</span>
                : <span data-testid={`badge-${p.id}`} className="text-xs text-slate-500 bg-slate-50 border border-slate-200 rounded-full px-2 py-0.5">未连接</span>}
            </div>
            <p className="text-xs text-slate-400">{p.hint}</p>
            <textarea
              data-testid={`secret-${p.id}`}
              rows={3}
              value={drafts[p.id]}
              onChange={e => setDrafts(d => ({ ...d, [p.id]: e.target.value }))}
              placeholder={connected ? '已连接 · 如需更新可粘贴新凭据' : '在此粘贴凭据…'}
              className="w-full resize-none rounded-xl border border-slate-200 px-3 py-2 text-sm font-mono outline-none focus:border-[#6366F1]" />
            <div className="flex gap-2">
              <button
                data-testid={`connect-${p.id}`}
                onClick={() => connect(p.id)}
                disabled={busy === p.id || !drafts[p.id].trim()}
                className="text-white text-sm font-medium px-3.5 py-1.5 rounded-xl cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                style={{ background: BRAND }}>
                {connected ? '更新连接' : '连接'}
              </button>
              {connected && (
                <button
                  data-testid={`disconnect-${p.id}`}
                  onClick={() => disconnect(p.id)}
                  disabled={busy === p.id}
                  className="border border-slate-300 text-slate-600 text-sm px-3.5 py-1.5 rounded-xl cursor-pointer hover:bg-slate-50 disabled:opacity-50">
                  断开
                </button>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}
