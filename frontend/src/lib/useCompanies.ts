import { useQuery } from '@tanstack/react-query'

import { api } from './api'
import type { CompanyListItem } from './types'

/** Действующие организации, доступные пользователю. */
export const useCompanies = () =>
  useQuery({
    queryKey: ['companies', false, ''],
    queryFn: () => api<CompanyListItem[]>('/companies'),
  })

/** Что нужно сделать по организации: нет суммы или клиент не получает напоминания. */
export const attentionReasons = (company: CompanyListItem) =>
  [
    company.has_missing_amount && 'есть задачи без суммы',
    company.has_blocked_member && 'клиент заблокировал бота',
  ].filter((reason): reason is string => !!reason)

/** Эти организации считает число в меню, и они отмечены в списке. */
export const needsAttention = (company: CompanyListItem) => attentionReasons(company).length > 0
