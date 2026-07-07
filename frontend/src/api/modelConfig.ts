import { api } from './client'

// 模型配置客户端(每企业统一管模型凭据 · ADR-028)。凭据由企业管理员在「模型配置」页
// 集中配置,注入本企业沙箱;agent 不再自带 key。全经 BFF 同源反代(/v1/ws/model-config),
// 凭 BFF HttpOnly 会话 cookie;PUT/DELETE 由 client.ts 双提交 CSRF。
//
// 红线:GET 只回状态(是否已配 + auth 类型 + 是否有 base_url),【绝不返回密钥值】;
// 前端永不回显已存密钥。角色门为 UX(服务端对非企业管理员 403 兜底)。

// auth 类型:subscription = 登录/订阅 token;api_key = API 密钥。每 provider 存一种(设一个替换另一个)。
export type AuthType = 'subscription' | 'api_key'

// 单 provider 状态(GET 返回)。二态:本企业已配(configured)/ 未配置。
// 所有 provider(含 anthropic)一律每企业各配,无平台默认。
export interface ProviderStatus {
  provider: string
  configured: boolean
  auth_type?: AuthType | null
  has_base_url?: boolean
}

// 设置入参(PUT body)。value=密钥/token 字面值(password 输入);base_url 仅支持的 provider 可带。
export interface SetModelConfigInput {
  auth_type: AuthType
  value: string
  base_url?: string
}

// provider 定义表(镜像 BFF):provider → 展示名 + 可选 auth 类型 + 是否支持 base_url。
// 顺序即页面展示顺序。auth 数组首项为该 provider 的默认。
export interface ProviderDef {
  provider: string
  label: string
  authOptions: AuthType[]
  supportsBaseUrl: boolean
}

export const PROVIDERS: ProviderDef[] = [
  { provider: 'anthropic', label: 'Anthropic (Claude)', authOptions: ['api_key'], supportsBaseUrl: true },
  { provider: 'openai', label: 'OpenAI (Codex)', authOptions: ['api_key', 'subscription'], supportsBaseUrl: true },
  { provider: 'minimax', label: 'MiniMax', authOptions: ['api_key'], supportsBaseUrl: true },
  { provider: 'deepseek', label: 'DeepSeek', authOptions: ['api_key'], supportsBaseUrl: true },
]

// auth 类型中文标签(展示用)。
export function authTypeLabel(t: AuthType): string {
  return t === 'subscription' ? '订阅 token' : 'API key'
}

interface ModelConfigResponse { providers?: ProviderStatus[] }

// 列出各 provider 配置状态(仅企业管理员;非管理员 → 服务端 403)。只回状态,无密钥值。
export async function listModelConfig(): Promise<ProviderStatus[]> {
  const r: ModelConfigResponse = await api.get('/v1/ws/model-config')
  return r?.providers ?? []
}

// 设置某 provider 凭据(企业管理员)。写本企业凭据文件;密钥不进日志/响应。
// 失败时 api.put 抛 Error(`${status}`)——含 403(非管理员)/400(字段),由调用方提示。
export async function setModelConfig(provider: string, input: SetModelConfigInput): Promise<void> {
  const body: SetModelConfigInput = { auth_type: input.auth_type, value: input.value.trim() }
  if (input.base_url?.trim()) body.base_url = input.base_url.trim()
  await api.put(`/v1/ws/model-config/${encodeURIComponent(provider)}`, body)
}

// 清除某 provider 凭据(企业管理员)。
export async function clearModelConfig(provider: string): Promise<void> {
  await api.delete(`/v1/ws/model-config/${encodeURIComponent(provider)}`)
}
