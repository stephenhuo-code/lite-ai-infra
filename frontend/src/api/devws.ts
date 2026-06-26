// BFF 客户端(Dev Workspace,plan 9b)。前端不持 token,全走我们的 BFF 反代。
// 工作目录/git 数据经 BFF → omnigent filesystem / 我们的 git 工具(具体形态待 9b/9d 探针;
// 此处为骨架,best-effort,失败回空,不阻塞外壳渲染)。
export interface WsSession { session_id: string }

export async function createWorkspaceSession(csrf: string): Promise<WsSession> {
  const r = await fetch('/v1/ws/sessions', { method: 'POST', headers: { 'x-csrf-token': csrf } })
  if (!r.ok) throw new Error(`create ws session failed: ${r.status}`)
  return r.json()
}

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
