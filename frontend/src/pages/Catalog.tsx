import { useCallback, useEffect, useMemo, useState } from 'react'
import { listCatalogs, listSchemas, listDatasets } from '../api/catalog'
import type { Dataset } from '../api/catalog'

// 数据目录 Catalog Explorer 两栏(US3):左=目录树(可展开/折叠)、右=详情。
// 层级:企业(metalake) → catalog → schema → 数据集(fileset),逐层点开加载下一层。
// 这是只读浏览/发现视图,区别于「数据集」页(管理)。
// 本轮 Tab 仅 概览/详情;禁出现 权限/策略 Tab、共享/注册/+添加标签/树「新建」按钮(spec Out)。
// 不显 e-/g- 原始 ID(FR-004):顶层企业标签显示「我的企业」,不显 metalake ID。
// 视觉照高保真原型 2026-06-22-data-domain-hifi.html 数据目录段(靛蓝 #6366F1)。

const BRAND = '#6366F1'
const BRAND_DARK = '#4F46E5'

function dash(v: string | number | null | undefined): string {
  return v === null || v === undefined || v === '' ? '—' : String(v)
}

// 缺值占位:注册时间取 created_at(契约字段),仅显日期部分。
function fmtDate(v: string | null | undefined): string {
  if (!v) return '—'
  return v.length >= 10 ? v.slice(0, 10) : v
}

function scopeLabel(s: Dataset['scope'] | undefined): string {
  if (s === 'shared') return '已共享'
  if (s === 'private') return '私有'
  return '—'
}

const chevron = (open: boolean) => (
  <svg
    className={`w-3.5 h-3.5 text-slate-400 transition-transform ${open ? 'rotate-90' : ''}`}
    fill="none" stroke="currentColor" strokeWidth="2.2" viewBox="0 0 24 24"
  ><path d="M9 6l6 6-6 6" /></svg>
)

const iconCatalog = (
  <svg className="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" strokeWidth="1.7" viewBox="0 0 24 24"><ellipse cx="12" cy="5" rx="8" ry="3" /><path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6" /></svg>
)
const iconSchema = (
  <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth="1.7" viewBox="0 0 24 24"><path d="M3 7l9-4 9 4-9 4-9-4z" /><path d="M3 12l9 4 9-4M3 17l9 4 9-4" /></svg>
)
const iconDataset = (
  <svg className="w-3.5 h-3.5 text-slate-400" fill="none" stroke="currentColor" strokeWidth="1.7" viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2" /><path d="M3 9h18M9 21V9" /></svg>
)

type Tab = 'overview' | 'detail'

// 选中的 schema 坐标。
type Selection = { catalog: string; schema: string }

export function Catalog() {
  // 树:企业 → catalogs。catalog/ schema 的展开状态与子项缓存。
  const [enterpriseOpen, setEnterpriseOpen] = useState(true)
  const [catalogs, setCatalogs] = useState<string[]>([])
  const [loadingCatalogs, setLoadingCatalogs] = useState(true)
  const [treeError, setTreeError] = useState('')

  // 每个 catalog 的展开态 + 其 schemas(惰性加载)。
  const [openCatalogs, setOpenCatalogs] = useState<Record<string, boolean>>({})
  const [schemas, setSchemas] = useState<Record<string, string[]>>({})

  // 每个 schema(键 `${catalog}/${schema}`)的展开态 + 其 datasets(惰性加载)。
  const [openSchemas, setOpenSchemas] = useState<Record<string, boolean>>({})
  const [datasets, setDatasets] = useState<Record<string, Dataset[]>>({})

  const [selected, setSelected] = useState<Selection | null>(null)
  const [tab, setTab] = useState<Tab>('overview')

  useEffect(() => {
    listCatalogs()
      .then(res => setCatalogs(res.names ?? []))
      .catch((e: unknown) => setTreeError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoadingCatalogs(false))
  }, [])

  const toggleCatalog = useCallback((c: string) => {
    setOpenCatalogs(prev => ({ ...prev, [c]: !prev[c] }))
    setSchemas(prev => {
      if (prev[c]) return prev // 已加载,仅切展开态
      listSchemas(c)
        .then(res => setSchemas(p => ({ ...p, [c]: res.names ?? [] })))
        .catch(() => setSchemas(p => ({ ...p, [c]: [] })))
      return prev
    })
  }, [])

  const schemaKey = (c: string, s: string) => `${c}/${s}`

  const toggleSchema = useCallback((c: string, s: string) => {
    const key = schemaKey(c, s)
    setOpenSchemas(prev => ({ ...prev, [key]: !prev[key] }))
    setDatasets(prev => {
      if (prev[key]) return prev
      listDatasets(c, s)
        .then(res => setDatasets(p => ({ ...p, [key]: res.datasets ?? [] })))
        .catch(() => setDatasets(p => ({ ...p, [key]: [] })))
      return prev
    })
  }, [])

  // 选中 schema:高亮 + 右栏渲染;同时确保其 datasets 已加载(供概览清单)。
  const selectSchema = useCallback((c: string, s: string) => {
    setSelected({ catalog: c, schema: s })
    setTab('overview')
    const key = schemaKey(c, s)
    setDatasets(prev => {
      if (prev[key]) return prev
      listDatasets(c, s)
        .then(res => setDatasets(p => ({ ...p, [key]: res.datasets ?? [] })))
        .catch(() => setDatasets(p => ({ ...p, [key]: [] })))
      return prev
    })
  }, [])

  const selectedDatasets = useMemo(() => {
    if (!selected) return []
    return datasets[schemaKey(selected.catalog, selected.schema)] ?? []
  }, [selected, datasets])

  return (
    <div className="-m-7 flex h-[calc(100vh-4rem)]">
      {/* 左:目录树 */}
      <div className="w-72 shrink-0 border-r border-slate-200/70 bg-white flex flex-col">
        <div className="px-4 py-3 flex items-center gap-2 border-b border-slate-100">
          <span className="font-semibold text-sm">Catalog</span>
        </div>
        <div className="flex-1 overflow-auto p-2 text-sm">
          {loadingCatalogs && <div className="px-2 py-2 text-slate-400">加载中…</div>}
          {!loadingCatalogs && treeError && (
            <div className="px-2 py-2 text-red-500">加载失败:{treeError}</div>
          )}
          {!loadingCatalogs && !treeError && (
            <>
              {/* metalake = 企业(v1 单企业,不显 e- ID) */}
              <button
                onClick={() => setEnterpriseOpen(o => !o)}
                className="w-full flex items-center gap-1.5 px-2 py-1.5 rounded-lg hover:bg-slate-50 text-slate-700"
              >
                {chevron(enterpriseOpen)}
                <svg className="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" strokeWidth="1.7" viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M3 9h18" /></svg>
                我的企业 <span className="text-[10px] text-slate-400 ml-1">metalake</span>
              </button>

              {enterpriseOpen && (
                <div className="ml-3 pl-2 border-l border-slate-100">
                  {catalogs.length === 0 && (
                    <div className="px-2 py-1.5 text-slate-400 text-[13px]">暂无 catalog</div>
                  )}
                  {catalogs.map(c => {
                    const cOpen = !!openCatalogs[c]
                    const cSchemas = schemas[c]
                    return (
                      <div key={c}>
                        <button
                          onClick={() => toggleCatalog(c)}
                          className="w-full flex items-center gap-1.5 px-2 py-1.5 rounded-lg hover:bg-slate-50 text-slate-700"
                        >
                          {chevron(cOpen)}
                          {iconCatalog}
                          {c}
                        </button>
                        {cOpen && (
                          <div className="ml-3 pl-2 border-l border-slate-100">
                            {cSchemas === undefined && (
                              <div className="px-2 py-1 text-slate-400 text-[13px]">加载中…</div>
                            )}
                            {cSchemas !== undefined && cSchemas.length === 0 && (
                              <div className="px-2 py-1 text-slate-400 text-[13px]">暂无 schema</div>
                            )}
                            {(cSchemas ?? []).map(s => {
                              const key = schemaKey(c, s)
                              const sOpen = !!openSchemas[key]
                              const isSel = selected?.catalog === c && selected?.schema === s
                              const sDatasets = datasets[key]
                              return (
                                <div key={s}>
                                  <div
                                    className={`w-full flex items-center gap-1.5 px-2 py-1.5 rounded-lg ${
                                      isSel ? 'bg-[#EEF0FF] text-[#4F46E5] font-medium' : 'hover:bg-slate-50 text-slate-700'
                                    }`}
                                  >
                                    <button
                                      onClick={() => toggleSchema(c, s)}
                                      aria-label={`展开 ${s}`}
                                      className="shrink-0"
                                    >
                                      {chevron(sOpen)}
                                    </button>
                                    <button
                                      onClick={() => selectSchema(c, s)}
                                      className="flex items-center gap-1.5 flex-1 text-left"
                                    >
                                      {iconSchema}
                                      {s}
                                    </button>
                                  </div>
                                  {sOpen && (
                                    <div className="ml-6 space-y-0.5 py-0.5">
                                      {sDatasets === undefined && (
                                        <div className="px-2 py-1 text-slate-400 text-[13px]">加载中…</div>
                                      )}
                                      {sDatasets !== undefined && sDatasets.length === 0 && (
                                        <div className="px-2 py-1 text-slate-400 text-[13px]">暂无数据集</div>
                                      )}
                                      {(sDatasets ?? []).map(d => (
                                        <button
                                          key={d.name}
                                          onClick={() => selectSchema(c, s)}
                                          className="w-full flex items-center gap-1.5 px-2 py-1 rounded-lg hover:bg-slate-50 text-slate-600 text-[13px]"
                                        >
                                          {iconDataset}
                                          {d.name}
                                        </button>
                                      ))}
                                    </div>
                                  )}
                                </div>
                              )
                            })}
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {/* 右:详情 */}
      <div className="flex-1 min-w-0 overflow-auto bg-slate-50">
        {!selected && (
          <div className="h-full grid place-items-center text-sm text-slate-400">
            从左侧目录树选择一个 schema 查看详情
          </div>
        )}
        {selected && (
          <>
            <div className="px-6 pt-5">
              {/* 面包屑:Catalog Explorer › {catalog} › {schema} */}
              <div className="flex items-center gap-1.5 text-xs text-slate-400 mb-3">
                <span>Catalog Explorer</span>
                <svg className="w-3 h-3" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path d="M9 6l6 6-6 6" /></svg>
                <span>{selected.catalog}</span>
                <svg className="w-3 h-3" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path d="M9 6l6 6-6 6" /></svg>
                <span className="text-slate-600">{selected.schema}</span>
              </div>
              <div className="flex items-center gap-3 mb-4">
                <svg className="w-6 h-6" style={{ color: BRAND }} fill="none" stroke="currentColor" strokeWidth="1.6" viewBox="0 0 24 24"><path d="M3 7l9-4 9 4-9 4-9-4z" /><path d="M3 12l9 4 9-4M3 17l9 4 9-4" /></svg>
                <h2 className="text-xl font-semibold">{selected.schema}</h2>
                <span className="text-xs text-slate-400 border border-slate-200 rounded px-1.5 py-0.5">schema</span>
              </div>
              {/* Tab 仅 概览/详情(禁权限/策略) */}
              <div className="flex items-center gap-5 text-sm border-b border-slate-200 mb-4">
                <button
                  onClick={() => setTab('overview')}
                  className={`pb-2.5 ${tab === 'overview' ? 'border-b-2 font-medium' : 'text-slate-500 hover:text-slate-700'}`}
                  style={tab === 'overview' ? { borderColor: BRAND, color: BRAND_DARK } : undefined}
                >概览</button>
                <button
                  onClick={() => setTab('detail')}
                  className={`pb-2.5 ${tab === 'detail' ? 'border-b-2 font-medium' : 'text-slate-500 hover:text-slate-700'}`}
                  style={tab === 'detail' ? { borderColor: BRAND, color: BRAND_DARK } : undefined}
                >详情</button>
              </div>
            </div>

            <div className="px-6 pb-6">
              {tab === 'overview' && (
                <>
                  {/* 概览 = 该 schema 下数据集清单:名称/owner/格式/注册时间/scope */}
                  <div className="bg-white border border-slate-200/70 rounded-2xl p-4 shadow-sm mb-5">
                    <table className="w-full text-sm">
                      <thead className="text-slate-500 text-xs border-b border-slate-100">
                        <tr className="text-left">
                          <th className="font-medium py-2">名称</th>
                          <th className="font-medium py-2">owner</th>
                          <th className="font-medium py-2">格式</th>
                          <th className="font-medium py-2">注册时间</th>
                          <th className="font-medium py-2">scope</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100">
                        {selectedDatasets.length === 0 && (
                          <tr><td colSpan={5} className="py-6 text-center text-slate-400">暂无数据集</td></tr>
                        )}
                        {selectedDatasets.map(d => (
                          <tr key={d.name}>
                            <td className="py-2.5 pr-4">
                              <span className="font-medium inline-flex items-center gap-1.5" style={{ color: BRAND_DARK }}>
                                {iconDataset}{d.name}
                              </span>
                            </td>
                            <td className="py-2.5 pr-4 text-slate-600">{dash(d.owner)}</td>
                            <td className="py-2.5 pr-4 text-slate-500">{dash(d.format)}</td>
                            <td className="py-2.5 pr-4 text-slate-500">{fmtDate(d.created_at)}</td>
                            <td className="py-2.5 pr-4 text-slate-500">{scopeLabel(d.scope)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  {/* 关于此 Schema:状态/owner/catalog */}
                  <h3 className="text-sm font-semibold mb-3">关于此 Schema</h3>
                  <dl className="grid grid-cols-[120px_1fr] gap-y-2.5 text-sm max-w-md">
                    <dt className="text-slate-500">状态</dt>
                    <dd className="flex items-center gap-1.5 text-emerald-600">
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth="2.2" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9" /><path d="M8 12l3 3 5-5" /></svg>
                      Active
                    </dd>
                    <dt className="text-slate-500">Owner</dt>
                    <dd className="text-slate-700">{dash(selectedDatasets[0]?.owner)}</dd>
                    <dt className="text-slate-500">Catalog</dt>
                    <dd className="text-slate-600">{selected.catalog}</dd>
                  </dl>
                </>
              )}

              {tab === 'detail' && (
                <div className="bg-white border border-slate-200/70 rounded-2xl p-8 shadow-sm text-sm text-slate-400 text-center">
                  详情视图建设中
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
