import { api } from './client'
import type { ChatItem } from '../pages/devws/useSessionStream'

// omnigent BFF 客户端(Plan 9a · Task T5)。前端不持 omnigent token,全经 BFF 同源反代
// (/v1/ws/*),凭 BFF HttpOnly 会话 cookie;变更请求由 client.ts 双提交 CSRF。
// 端点形态以 T4 反代(services/gateway/bff/omnigent_proxy.py)+ P1 探针实测为准。

export interface Agent { id: string; name: string }
export interface Session { id: string; title?: string | null }

// 智能体库条目(ADR-027)。BFF GET /v1/ws/agents 已按企业过滤 + 剥企业前缀,
// 故 name = 干净展示名;builtin=全局内置模板、enterprise_owned=本企业创建。
export interface LibraryAgent {
  id: string
  name: string
  harness?: string | null
  description?: string | null
  builtin?: boolean
  enterprise_owned?: boolean
}

// 创建智能体入参(仅企业管理员;服务端 can() 强制,非管理员 403)。
// 9a 范围:只 name(必填)/ instructions / model / harness(仅 claude-native)。
// 无 MCP/工具/数据/per-agent 凭据(那是 9b)。
export interface CreateAgentInput {
  name: string
  instructions?: string
  model?: string
  harness?: string
  description?: string
}

// claude-native-ui 默认 agent(探针 live-pinned);无显式选择时回退此。
export const DEFAULT_AGENT_ID = 'ag_58a1bc5bf0bba6d31ceeb7661f8d751c'

// omnigent 列表响应统一 { data: [...] }(反代原状透传)。
interface DataEnvelope<T> { data?: T[] }

// 会话条目:message 条目带 role(user/assistant)+ content 块。实测内容类型:
// user→`input_text`、assistant→`output_text`(也容忍裸 `text`);非 message 条目
// (resource_event 等)无 role,在 mapItems 里按 role 丢弃。
const TEXT_CONTENT_TYPES = new Set(['text', 'input_text', 'output_text'])
interface OmniContent { type?: string; text?: string }
interface OmniItem { id?: string; role?: string; content?: OmniContent[] }

export async function listAgents(): Promise<Agent[]> {
  const r: DataEnvelope<Agent> = await api.get('/v1/ws/agents')
  return r?.data ?? []
}

// 智能体库列表(含 builtin/enterprise_owned 标志,供「智能体库」页 + 对话选择器用)。
export async function listLibraryAgents(): Promise<LibraryAgent[]> {
  const r: DataEnvelope<LibraryAgent> = await api.get('/v1/ws/agents')
  return r?.data ?? []
}

// 创建智能体(企业管理员)。harness 默认 claude-native(唯一注入全局订阅的)。
// 失败时 api.post 抛 Error(`${status}`)——含 403(非管理员)/4xx(重名/字段门),由调用方提示。
export async function createAgent(input: CreateAgentInput): Promise<LibraryAgent> {
  const body: CreateAgentInput = { name: input.name.trim(), harness: input.harness || 'claude-native' }
  if (input.instructions?.trim()) body.instructions = input.instructions.trim()
  if (input.model?.trim()) body.model = input.model.trim()
  if (input.description?.trim()) body.description = input.description.trim()
  return api.post('/v1/ws/agents', body)
}

export async function listSessions(): Promise<Session[]> {
  const r: DataEnvelope<Session> = await api.get('/v1/ws/sessions')
  return r?.data ?? []
}

export async function createSession(agentId: string): Promise<Session> {
  const r: { id?: string } = await api.post('/v1/ws/sessions', { agent_id: agentId })
  return { id: r?.id ?? '' }
}

export async function sendTurn(sessionId: string, text: string): Promise<void> {
  await api.post(`/v1/ws/sessions/${encodeURIComponent(sessionId)}/turn`, { text })
}

// 把 omnigent 会话条目映射成 9a 的 ChatItem[](role→kind,拼接 text content)。
// 非 user/assistant 的 role(tool/system 等)在 9a 一律丢弃 —— 9a = 纯文本对话。
export function mapItems(raw: OmniItem[]): ChatItem[] {
  const out: ChatItem[] = []
  for (const it of raw) {
    const kind = it?.role === 'user' ? 'user' : it?.role === 'assistant' ? 'assistant' : null
    if (!kind) continue
    const text = (it?.content ?? [])
      .filter(c => TEXT_CONTENT_TYPES.has(c?.type ?? ''))
      .map(c => c?.text ?? '')
      .join('')
    out.push({ kind, text })
  }
  return out
}

// 对话历史(claude-native 回复以 items 为权威源)。
export async function fetchSessionItems(sessionId: string): Promise<ChatItem[]> {
  const r: DataEnvelope<OmniItem> = await api.get(
    `/v1/ws/sessions/${encodeURIComponent(sessionId)}/items`)
  return mapItems(r?.data ?? [])
}
