import { useQuery } from '@tanstack/react-query'

import { api } from '../../lib/api'
import type { StaffMember } from '../../lib/types'

/** Кому можно назначить компанию (список доступен только администратору). */
export function useStaff(enabled: boolean) {
  return useQuery({
    queryKey: ['staff'],
    queryFn: () => api<StaffMember[]>('/staff'),
    enabled,
    refetchOnMount: 'always',
  })
}
