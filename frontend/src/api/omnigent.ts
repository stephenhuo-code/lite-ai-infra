import { api } from './client'
import type { ChatItem } from '../pages/devws/useSessionStream'

// omnigent BFF 客户端(Plan 9a · Task T5)。前端不持 omnigent token,全经 BFF 同源反代
// (/v1/ws/*),凭 BFF HttpOnly 会话 cookie;变更请求由 client.ts 双提交 CSRF。
// 端点形态以 T4 反代(services/gateway/bff/omnigent_proxy.py)+ P1 探针实测为准。

export interface Agent { id: string; name: string }
export interface Session { id: string; title?: string | null }

// claude-native-ui 默认 agent(探针 live-pinned);无显式选择时回退此。
export const DEFAULT_AGENT_ID = 'ag_58a1bc5bf0bba6d31ceeb7661f8d751c'

// omnigent 列表响应统一 { data: [...] }(反代原状透传)。
interface DataEnvelope<T> { data?: T[] }

// 会话条目:assistant/user role + content:[{type:'text'|'output_text', text}]。
interface OmniContent { type?: string; text?: string }
interface OmniItem { id?: string; role?: string; content?: OmniContent[] }

export async function listAgents(): Promise<Agent[]> {
  const r: DataEnvelope<Agent> = await api.get('/v1/ws/agents')
  return r?.data ?? []
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
      .filter(c => c?.type === 'text' || c?.type === 'output_text')
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
