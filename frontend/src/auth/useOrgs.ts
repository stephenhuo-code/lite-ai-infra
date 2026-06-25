import { useEffect, useState } from 'react'
import { api } from '../api/client'

// 字段以真实 GET /v1/me/orgs 响应为准(契约 contracts/openapi/identity-org.yaml,
// 后端 services/identity_org_service/app.py):
// {user, is_platform_admin, memberships: [{enterprise_id, role}], enterprises: [{alias, display_name}]}。
// 身份降两级(ADR-025):无访问组层;role ∈ member|enterprise-admin(真实角色,
// 不可用 is_platform_admin 派生)。enterprise_id/alias 是不透明 ID,前端内部可持有,
// 但 §1.4/FR-004 禁止渲染到界面 —— 界面用 enterprises[].display_name(FR-002b)。
export type Membership = {
  enterprise_id: string
  role: string // member | enterprise-admin
}
export type Enterprise = {
  alias: string
  display_name?: string | null // 企业显示名(界面渲染;可空时回退 alias)
}
export type Orgs = {
  user: string
  is_platform_admin: boolean
  memberships: Membership[]
  enterprises?: Enterprise[]
}

export function useOrgs() {
  const [orgs, setOrgs] = useState<Orgs | null>(null)
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    api.get('/v1/me/orgs').then(setOrgs).catch(() => {}).finally(() => setLoading(false))
  }, [])
  return { orgs, loading }
}
