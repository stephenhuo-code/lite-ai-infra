import { useEffect, useState } from 'react'
import { api } from '../api/client'

// 字段以真实 /auth/me 响应为准(services/gateway/bff/middleware.py auth_me):
// {user, is_platform_admin, csrf}。FR-004:不返回 enterprise_name/memberships/e-/g- 内部 ID。
export type Me = {
  user: string
  is_platform_admin: boolean
  csrf?: string
}

export function useMe() {
  const [me, setMe] = useState<Me | null>(null)
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    api.get('/auth/me').then(setMe).catch(() => {}).finally(() => setLoading(false))
  }, [])
  return { me, loading }
}
