import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useSyncExternalStore } from 'react'

import { api, session } from './lib/api'
import type { User } from './lib/types'

const hasSession = () => session.get() !== null

export function useAuth() {
  const queryClient = useQueryClient()
  const signedIn = useSyncExternalStore(session.subscribe, hasSession)
  const me = useQuery({ queryKey: ['me'], queryFn: () => api<User>('/me'), enabled: signedIn })

  const logout = useCallback(() => {
    session.clear()
    queryClient.clear()
  }, [queryClient])

  return { signedIn, user: signedIn ? me.data : undefined, error: me.error, logout }
}
