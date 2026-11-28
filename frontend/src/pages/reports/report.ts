export type Result = 'on_time' | 'late' | 'not_required' | 'overdue'

export const RESULT_NAMES: Record<Result, string> = {
  on_time: 'В срок',
  late: 'С опозданием',
  not_required: 'Не требуется',
  overdue: 'Просрочено',
}

export const RESULTS = Object.keys(RESULT_NAMES) as Result[]

export interface ReportTotal extends Record<Result, number> {
  accountant: string
  company: string
  company_id: number
  paid_kopecks: number
}

export interface ReportRow {
  task_id: number
  company_id: number
  result: Result
  accountant: string
  company: string
  title: string
  kind: string
  due: string
  status: string
  marked: string | null
  marked_by: string
  timing: string
  amount_kopecks: number | null
}

export interface Report {
  summary: ReportTotal[]
  tasks: number
  rows: ReportRow[]
}
