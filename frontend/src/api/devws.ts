// BFF 客户端(Dev Workspace,plan 9b)。前端不持 token,全经 BFF 反代;CSRF 双提交(csrf_token cookie)。
export interface WsSession { session_id: string }

function csrf(): string {
  const m = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/)
  return m ? decodeURIComponent(m[1]) : ''
}
function mut(body?: unknown): RequestInit {
  return { method: 'POST', headers: { 'Content-Type': 'application/json', 'x-csrf-token': csrf() },
           body: body === undefined ? undefined : JSON.stringify(body) }
}

export async function createWorkspaceSession(): Promise<WsSession> {
  const r = await fetch('/v1/ws/sessions', mut({}))
  if (!r.ok) throw new Error(`create ws session failed: ${r.status}`)
  return r.json()
}

export async function sendTurn(sessionId: string, text: string): Promise<void> {
  await fetch(`/v1/ws/sessions/${encodeURIComponent(sessionId)}/turn`, mut({ text }))
}

export async function resolveElicitation(sessionId: string, id: string, approve: boolean): Promise<void> {
  await fetch(`/v1/ws/sessions/${encodeURIComponent(sessionId)}/elicitations/${encodeURIComponent(id)}/resolve`, mut({ approve }))
}

// 工作目录树 / git 状态:经 BFF → omnigent filesystem / 我们的 git 工具(best-effort,失败回空,
// 不阻塞外壳;live 接入后填充)。
export async function fetchWorkingFiles(): Promise<string[]> {
  try {
    const r = await fetch('/v1/ws/working-files')
    return r.ok ? (await r.json()).files ?? [] : []
  } catch { return [] }
}

export async function fetchGitChanges(): Promise<{ x: string; path: string }[]> {
  try {
    const r = await fetch('/v1/ws/git-status')
    return r.ok ? (await r.json()).changes ?? [] : []
  } catch { return [] }
}
