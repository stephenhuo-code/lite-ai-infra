import { useEffect, useState } from 'react'
import { api } from '../api/client'

// 当前用户的真实展示信息,来自 BFF GET /auth/me(解会话内 access token claims)。
// username 优先 preferred_username、回退 name、再回退 sub;email 可空。
// user(sub,§1.4 不透明)仅供内部使用,界面展示用 username/email。
export type Me = {
  user: string
  username: string
  email?: string | null
  is_platform_admin: boolean
}

export function useMe() {
  const [me, setMe] = useState<Me | null>(null)
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    api.get('/auth/me').then(setMe).catch(() => {}).finally(() => setLoading(false))
  }, [])
  return { me, loading }
}
