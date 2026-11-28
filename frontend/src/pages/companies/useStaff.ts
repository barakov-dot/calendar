import { useQuery } from '@tanstack/react-query'

import { api } from '../../lib/api'
import type { StaffMember } from '../../lib/types'

/** Бухгалтеры и помощники для назначения (список доступен администратору и главному). */
export function useStaff(enabled: boolean) {
  return useQuery({
    queryKey: ['staff'],
    queryFn: () => api<StaffMember[]>('/staff'),
    enabled,
    refetchOnMount: 'always',
  })
}
