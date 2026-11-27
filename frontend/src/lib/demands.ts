import { useQuery } from '@tanstack/react-query'

import { api } from './api'
import type { TaskStatus } from './tasks'

export interface DemandStep {
  task_id: number
  due_date: string
  status: TaskStatus
}

export interface Demand {
  id: number
  company_id: number
  company_name: string
  knd: string
  name: string
  action: string
  response_label: string
  number: string
  doc_date: string
  sent_date: string
  receipt_date: string
  receipt_set: boolean
  response_workdays: number | null
  response_date: string
  response_set: boolean
  amount_kopecks: number | null
  note: string
  filename: string
  content_type: string
  closed: boolean
  receipt: DemandStep | null
  response: DemandStep | null
}

export interface DemandKind {
  knd: string
  name: string
  action: string
  response_label: string
  response_workdays: number | null
  is_payment: boolean
}

export interface Recognized {
  readable: boolean
  company_id: number | null
  inn: string
  knd: string
  number: string
  doc_date: string | null
  response_workdays: number | null
  response_date: string | null
  amount_kopecks: number | null
  note: string
}

export const useDemands = (enabled = true) =>
  useQuery({
    queryKey: ['demands'],
    queryFn: () => api<Demand[]>('/demands'),
    refetchOnMount: 'always',
    enabled,
  })

/** Ближайший невыполненный шаг; у закрытого требования — срок ответа. */
export function nextDue(demand: Demand): string {
  const open = [demand.receipt, demand.response].filter((step) => step?.status === 'planned')
  return open.map((step) => step!.due_date).sort()[0] ?? demand.response_date
}

/** Поля формы требования; пустые даты квитанции и ответа считает сервер. */
export interface DemandValues {
  company_id: number
  knd: string
  number: string
  doc_date: string
  sent_date: string
  receipt_date: string
  response_workdays: string
  response_date: string
  amount: string
  note: string
}

export const EMPTY_DEMAND: DemandValues = {
  company_id: 0,
  knd: '',
  number: '',
  doc_date: '',
  sent_date: '',
  receipt_date: '',
  response_workdays: '',
  response_date: '',
  amount: '',
  note: '',
}
