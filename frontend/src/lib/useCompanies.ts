import { useQuery } from '@tanstack/react-query'

import { api } from './api'
import type { CompanyListItem } from './types'

/** Действующие организации, доступные пользователю. */
export const useCompanies = () =>
  useQuery({
    queryKey: ['companies', false, ''],
    queryFn: () => api<CompanyListItem[]>('/companies'),
  })

/** Организации, где нужно что-то сделать: нет суммы или клиент не получает напоминания. */
export const needsAttention = (company: CompanyListItem) =>
  company.has_missing_amount || company.has_blocked_member
