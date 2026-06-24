import { useEffect, useState } from 'react'
import { api } from '../api/client'

// 字段以真实 GET /v1/me/orgs 响应为准(契约 contracts/openapi/identity-org.yaml,
// 后端 services/identity_org_service/app.py):
// {user, is_platform_admin, memberships: [{enterprise_id, group_id, role}]}。
// role ∈ member|group-admin|enterprise-admin —— 这是真实「组内角色」,
// 不可用 is_platform_admin(全局平台管理员标志)派生角色。
// 注意:enterprise_id/group_id 是 e-/g- 内部 ID,前端内部可持有(将来判断用),
// 但 FR-004 禁止渲染到界面。后端目前无企业/组「显示名」字段(vN+ 缺口)。
export type Membership = {
  enterprise_id: string
  group_id?: string | null
  role: string // member | group-admin | enterprise-admin
}
export type Orgs = {
  user: string
  is_platform_admin: boolean
  memberships: Membership[]
}

export function useOrgs() {
  const [orgs, setOrgs] = useState<Orgs | null>(null)
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    api.get('/v1/me/orgs').then(setOrgs).catch(() => {}).finally(() => setLoading(false))
  }, [])
  return { orgs, loading }
}
