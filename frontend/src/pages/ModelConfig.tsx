import { useCallback, useEffect, useState } from 'react'
import {
  listModelConfig, setModelConfig, clearModelConfig,
  PROVIDERS, authTypeLabel,
  type ProviderStatus, type ProviderDef, type AuthType,
} from '../api/modelConfig'
import { useOrgs } from '../auth/useOrgs'

// 模型配置页(每企业统一管模型凭据 · ADR-028)。企业管理员在此为本企业各 provider 配凭据
// (订阅 token / API key + 可选 base_url),注入本企业沙箱;agent 不再自带 key。
// 红线:GET 只回状态,前端【永不回显已存密钥】;角色门为 UX(服务端对非管理员 403 兜底)。
// 视觉照智能体库(靛蓝 #6366F1)。

// 是否为本企业管理员:任一 membership.role === 'enterprise-admin'。仅 UX 门——服务端独立强制。
function isEnterpriseAdmin(orgs: ReturnType<typeof useOrgs>['orgs']): boolean {
  return !!orgs?.memberships?.some(m => m.role === 'enterprise-admin')
}

// 形似变量引用的值(${FOO} 或 $FOO)——服务端只收字面值会 400。前端先拦,给友好提示。
function looksLikeVarRef(v: string): boolean {
  return /\$\{|\$[A-Za-z_]/.test(v)
}

// BFF 状态码 → 可理解中文(不裸露 HTTP 码)。
function errMessage(e: unknown): string {
  const msg = e instanceof Error ? e.message : String(e)
  if (msg === '403') return '你没有配置模型凭据的权限(需企业管理员)。'
  if (msg === '400') return '保存失败:字段无效(auth 类型 / 值 / base_url),请检查后再试。'
  return `保存失败:${msg}`
}

// 无权限提示(非企业管理员)。服务端也 403,此为 UX 门。
function NoPermissionNotice() {
  return (
    <div className="grid place-items-center" style={{ minHeight: '60vh' }}>
      <div className="text-center max-w-md px-6">
        <div className="mx-auto mb-4 h-14 w-14 rounded-2xl bg-[#EEF0FF] grid place-items-center" style={{ color: '#6366F1' }}>
          <svg className="w-7 h-7" fill="none" stroke="currentColor" strokeWidth="1.7" viewBox="0 0 24 24"><rect x="5" y="11" width="14" height="10" rx="2" /><path d="M8 11V7a4 4 0 018 0v4" /></svg>
        </div>
        <h2 className="text-lg font-semibold text-slate-800">仅企业管理员可访问</h2>
        <p className="text-sm text-slate-500 mt-2 leading-relaxed">
          模型配置由<b>企业管理员</b>统一管理本企业的模型凭据。你没有访问权限,请联系企业管理员。
        </p>
      </div>
    </div>
  )
}

// 配置表单(弹窗):auth 类型选择 + 值(password)+ 可选 base_url。保存 → setModelConfig。
function ConfigModal({ def, status, onClose, onDone }: {
  def: ProviderDef
  status: ProviderStatus | undefined
  onClose: () => void
  onDone: () => void
}) {
  const configured = status?.configured === true
  const platformDefault = !configured && status?.platform_default === true
  const [authType, setAuthType] = useState<AuthType>(def.authOptions[0])
  const [value, setValue] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [phase, setPhase] = useState<'idle' | 'submitting' | 'error'>('idle')
  const [err, setErr] = useState('')

  const canSubmit = value.trim() !== '' && phase !== 'submitting'

  // 客户端前置校验(镜像服务端门):值必填非空 + 拒变量引用形。
  function validate(): string | null {
    if (value.trim() === '') return '请填写值(密钥 / 订阅 token)。'
    if (looksLikeVarRef(value)) return '值不能是 ${VAR} / $VAR 形式的变量引用,请填入真实的字面值。'
    return null
  }

  async function submit() {
    const v = validate()
    if (v) { setErr(v); setPhase('error'); return }
    setPhase('submitting')
    setErr('')
    try {
      await setModelConfig(def.provider, {
        auth_type: authType,
        value: value.trim(),
        ...(def.supportsBaseUrl && baseUrl.trim() ? { base_url: baseUrl.trim() } : {}),
      })
      onDone()
    } catch (e) {
      setErr(errMessage(e))
      setPhase('error')
    }
  }

  const valueLabel = authType === 'subscription' ? '订阅 token *' : 'API key *'

  return (
    <div className="fixed inset-0 z-40 grid place-items-center px-4">
      <div className="absolute inset-0 bg-slate-900/30 backdrop-blur-[2px]" onClick={onClose} />
      <div className="relative bg-white w-full max-w-lg rounded-2xl shadow-xl border border-slate-200 p-6 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-5">
          <h2 className="font-semibold text-lg">{configured ? '修改' : platformDefault ? '覆盖' : '配置'} · {def.label}</h2>
          <button onClick={onClose} aria-label="关闭" className="text-slate-400 hover:text-slate-700">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path d="M18 6L6 18M6 6l12 12" /></svg>
          </button>
        </div>

        {configured && (
          <div className="mb-5 text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded-xl px-3.5 py-3">
            该 provider <strong>已配置</strong>。为安全起见已存的值不会回显;保存新值将<strong>整体替换</strong>当前凭据。
          </div>
        )}

        {platformDefault && (
          <div className="mb-5 text-sm text-slate-600 bg-[#EEF0FF] border border-[#C7CBFF] rounded-xl px-3.5 py-3">
            该 provider 当前用<strong>平台全局{status?.platform_auth_type ? authTypeLabel(status.platform_auth_type) : '订阅'}</strong>,agent 已可用。填入本企业自己的凭据将<strong>覆盖</strong>平台默认(仅本企业生效);清除后回落平台默认。
          </div>
        )}

        {/* auth 类型:仅当该 provider 有多个可选时显示选择器 */}
        {def.authOptions.length > 1 ? (
          <div className="mb-4">
            <label className="block text-xs font-medium text-slate-600 mb-1.5" htmlFor="mc-auth-type">凭据类型</label>
            <select
              id="mc-auth-type"
              value={authType}
              onChange={e => { setAuthType(e.target.value as AuthType); if (phase === 'error') { setErr(''); setPhase('idle') } }}
              aria-label="凭据类型"
              className="w-full rounded-xl border border-slate-300 px-3.5 py-2.5 text-sm focus:border-[#6366F1] outline-none bg-white"
            >
              {def.authOptions.map(a => <option key={a} value={a}>{authTypeLabel(a)}</option>)}
            </select>
            <p className="text-[11px] text-slate-400 mt-1.5">每个 provider 只保留一种凭据,设置其一将替换另一种。</p>
          </div>
        ) : (
          <div className="mb-4 text-xs text-slate-500">凭据类型:{authTypeLabel(def.authOptions[0])}</div>
        )}

        <div className="mb-4">
          <label className="block text-xs font-medium text-slate-600 mb-1.5" htmlFor="mc-value">{valueLabel}</label>
          <input
            id="mc-value"
            type="password"
            value={value}
            onChange={e => setValue(e.target.value)}
            placeholder={authType === 'subscription' ? '粘贴订阅 / 登录 token' : 'sk-...'}
            autoComplete="off"
            className="w-full rounded-xl border border-slate-300 px-3.5 py-2.5 text-sm focus:border-[#6366F1] outline-none"
          />
          <p className="text-[11px] text-slate-400 mt-1.5">填入真实字面值;为安全起见保存后不会回显。</p>
        </div>

        {def.supportsBaseUrl && (
          <div className="mb-4">
            <label className="block text-xs font-medium text-slate-600 mb-1.5" htmlFor="mc-base-url">Base URL(可选)</label>
            <input
              id="mc-base-url"
              value={baseUrl}
              onChange={e => setBaseUrl(e.target.value)}
              placeholder="留空用该 provider 默认 endpoint"
              className="w-full rounded-xl border border-slate-300 px-3.5 py-2.5 text-sm focus:border-[#6366F1] outline-none"
            />
          </div>
        )}

        {phase === 'error' && (
          <div className="mt-3.5 text-sm text-red-700 bg-red-50 border border-red-200 rounded-xl px-3.5 py-2.5">{err}</div>
        )}

        <div className="flex justify-end gap-2 mt-6">
          <button onClick={onClose} className="text-sm text-slate-600 px-4 py-2.5 rounded-xl hover:bg-slate-100">取消</button>
          <button
            onClick={submit}
            disabled={!canSubmit}
            className="text-sm font-medium text-white bg-[#6366F1] hover:bg-[#4F46E5] px-4 py-2.5 rounded-xl disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {phase === 'submitting' ? '保存中…' : phase === 'error' ? '重试' : '保存'}
          </button>
        </div>
      </div>
    </div>
  )
}

// 单 provider 行卡片。三态徽标:本企业已配 / 平台默认(全局订阅,agent 可跑,可覆盖)/ 未配置。
function ProviderRow({ def, status, canManage, onConfigure, onClear }: {
  def: ProviderDef
  status: ProviderStatus | undefined
  canManage: boolean
  onConfigure: (def: ProviderDef) => void
  onClear: (def: ProviderDef) => void
}) {
  const configured = status?.configured === true
  // 平台默认:本企业没配、但平台有全局默认(如 claude 订阅)→ agent 仍能跑,只是没用本企业自己的凭据。
  const platformDefault = !configured && status?.platform_default === true
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm flex items-start gap-3">
      <div aria-hidden="true" className="shrink-0 w-10 h-10 rounded-xl bg-[#EEF0FF] text-[#4F46E5] font-semibold flex items-center justify-center">
        {def.label[0]}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <h2 className="font-semibold text-slate-800 truncate">{def.label}</h2>
          {configured
            ? <span className="shrink-0 text-[11px] font-medium text-emerald-700 bg-emerald-50 rounded px-1.5 py-0.5">本企业已配置</span>
            : platformDefault
            ? <span className="shrink-0 text-[11px] font-medium text-[#4F46E5] bg-[#EEF0FF] rounded px-1.5 py-0.5">平台默认</span>
            : <span className="shrink-0 text-[11px] font-medium text-slate-500 bg-slate-100 rounded px-1.5 py-0.5">未配置</span>}
        </div>
        {configured ? (
          <div className="mt-1 text-xs text-slate-500 flex flex-wrap items-center gap-x-3 gap-y-1">
            <span>类型:{status?.auth_type ? authTypeLabel(status.auth_type) : '—'}</span>
            {/* 红线:永不回显密钥,仅掩码占位 */}
            <span className="font-mono text-slate-400">••••••已配置</span>
            {def.supportsBaseUrl && <span>base_url:{status?.has_base_url ? '已设置' : '默认'}</span>}
          </div>
        ) : platformDefault ? (
          <div className="mt-1 text-xs text-slate-500">
            使用<b>平台全局{status?.platform_auth_type ? authTypeLabel(status.platform_auth_type) : '订阅'}</b>,该 provider 的 agent 开箱即用;如需用本企业自己的凭据,可<b>覆盖</b>。
          </div>
        ) : (
          <div className="mt-1 text-xs text-slate-400">尚未为该 provider 配置凭据,相关 agent 暂不可用。</div>
        )}
      </div>
      {canManage && (
        <div className="shrink-0 flex items-center gap-1">
          <button
            onClick={() => onConfigure(def)}
            className="text-xs font-medium text-slate-500 hover:text-[#4F46E5] px-2 py-1 rounded-lg hover:bg-[#EEF0FF] transition-colors"
          >
            {configured ? '修改' : platformDefault ? '覆盖' : '配置'}
          </button>
          {configured && (
            <button
              onClick={() => onClear(def)}
              className="text-xs font-medium text-slate-500 hover:text-red-600 px-2 py-1 rounded-lg hover:bg-red-50 transition-colors"
            >
              清除
            </button>
          )}
        </div>
      )}
    </div>
  )
}

export function ModelConfig() {
  const { orgs, loading: orgsLoading } = useOrgs()
  const isAdmin = isEnterpriseAdmin(orgs)

  const [statuses, setStatuses] = useState<ProviderStatus[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [editDef, setEditDef] = useState<ProviderDef | null>(null)

  const load = useCallback(() => {
    return listModelConfig()
      .then(setStatuses)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    // 仅管理员拉取(非管理员不发请求,避免徒劳 403 + 早返回渲染无权限提示,不看 loading);
    // 等 orgs 加载完再定夺。
    if (orgsLoading || !isAdmin) return
    void load()
  }, [orgsLoading, isAdmin, load])

  const statusOf = (provider: string) => statuses.find(s => s.provider === provider)

  async function handleClear(def: ProviderDef) {
    if (!window.confirm(`确认清除 ${def.label} 的凭据?清除后本企业使用该 provider 的 agent 将无法调用。`)) return
    try {
      await clearModelConfig(def.provider)
      setLoading(true); setError(''); void load()
    } catch (e) {
      setError(errMessage(e))
    }
  }

  // 角色门:等 orgs 加载完;非管理员 → 无权限提示。
  if (!orgsLoading && !isAdmin) return <NoPermissionNotice />

  return (
    <div>
      <div className="mb-4">
        <h1 className="text-lg font-semibold text-slate-800">模型配置</h1>
        <p className="text-sm text-slate-500 mt-0.5">
          统一管理本企业各模型 provider 的凭据(订阅 token / API key)。配置后自动注入本企业智能体沙箱,agent 无需自带 key。
        </p>
      </div>

      {(loading || orgsLoading) && (
        <div className="space-y-3">
          {PROVIDERS.map(p => (
            <div key={p.provider} className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm animate-pulse flex items-start gap-3">
              <div className="shrink-0 w-10 h-10 rounded-xl bg-slate-100" />
              <div className="flex-1 space-y-2 pt-1">
                <div className="h-4 w-1/3 bg-slate-100 rounded" />
                <div className="h-3 w-1/2 bg-slate-100 rounded" />
              </div>
            </div>
          ))}
        </div>
      )}

      {!loading && !orgsLoading && error && (
        <div className="rounded-2xl border border-red-200 bg-red-50 p-8 text-center text-sm text-red-600">
          加载失败:{error === '403' ? '需企业管理员权限' : error}
        </div>
      )}

      {!loading && !orgsLoading && !error && (
        <div className="space-y-3">
          {PROVIDERS.map(def => (
            <ProviderRow
              key={def.provider}
              def={def}
              status={statusOf(def.provider)}
              canManage={isAdmin}
              onConfigure={setEditDef}
              onClear={handleClear}
            />
          ))}
        </div>
      )}

      {editDef && (
        <ConfigModal
          def={editDef}
          status={statusOf(editDef.provider)}
          onClose={() => setEditDef(null)}
          onDone={() => { setEditDef(null); setLoading(true); setError(''); void load() }}
        />
      )}
    </div>
  )
}
