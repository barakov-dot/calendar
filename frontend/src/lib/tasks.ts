export type TaskKind = 'payment' | 'report' | 'notice' | 'other'
export type TaskStatus = 'planned' | 'done' | 'paid' | 'not_required'

export const KIND_NAMES: Record<TaskKind, string> = {
  payment: 'Платёж',
  report: 'Отчёт',
  notice: 'Уведомление',
  other: 'Другое',
}

export const STATUS_NAMES: Record<TaskStatus, string> = {
  planned: 'Запланировано',
  paid: 'Оплачено',
  done: 'Сдано',
  not_required: 'Не требуется',
}

export interface Task {
  id: number
  company_id: number | null
  company_name: string
  kind: TaskKind
  title: string
  due_date: string
  amount_kopecks: number | null
  status: TaskStatus
  client_note: string
  source_ref: string
  source: 'rule' | 'custom'
  needs_amount: boolean
  can_mark_paid: boolean
  can_unmark_paid: boolean
}

export interface NdsPart {
  id: number
  part: number
  due_date: string
  amount_kopecks: number | null
  amount_overridden: boolean
  status: TaskStatus
}

export interface TaskDetail extends Task {
  rule_code: string | null
  period_key: string | null
  part: number
  description: string
  original_due_date: string
  due_overridden: boolean
  amount_overridden: boolean
  client_visible: boolean
  comment: string
  status_changed_at: string | null
  status_changed_by_name: string
  status_changed_by_role: string | null
  recurring_reminder_id: number | null
  nds_parts: NdsPart[]
}

export interface TaskListResponse {
  items: Task[]
  total: number
  today: string
}

/** Как статус называется для клиента. */
export function clientStatus(task: Pick<Task, 'kind' | 'status'>): string {
  if (task.status === 'paid') return 'Оплачено ✓'
  if (task.status === 'done') return task.kind === 'report' ? 'Сдано ✓' : 'Выполнено ✓'
  if (task.status === 'not_required') return 'Не требуется'
  return task.kind === 'payment' ? 'К оплате' : 'Готовится'
}

/** Статусы, применимые к задаче такого типа (так же проверяет сервер). */
export const statusesFor = (kind: TaskKind): TaskStatus[] => [
  'planned',
  kind === 'payment' ? 'paid' : 'done',
  'not_required',
]

export type Tone = 'overdue' | 'planned' | 'closed' | 'skipped'

export function toneOf(task: Pick<Task, 'status' | 'due_date'>, today: string): Tone {
  if (task.status === 'not_required') return 'skipped'
  if (task.status !== 'planned') return 'closed'
  return task.due_date < today ? 'overdue' : 'planned'
}

const moscowDate = new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Moscow' })

/** Сегодняшняя дата по Москве в виде ГГГГ-ММ-ДД. */
export const todayIso = (now = new Date()) => moscowDate.format(now)

export function addDays(iso: string, days: number): string {
  const date = new Date(`${iso}T00:00:00Z`)
  date.setUTCDate(date.getUTCDate() + days)
  return date.toISOString().slice(0, 10)
}

export function addMonths(month: string, delta: number): string {
  const [year, number] = month.split('-').map(Number)
  return new Date(Date.UTC(year, number - 1 + delta, 1)).toISOString().slice(0, 7)
}

/** Недели месяца с понедельника; null — клетки соседних месяцев. */
export function monthGrid(month: string): (string | null)[][] {
  const first = `${month}-01`
  const offset = (new Date(`${first}T00:00:00Z`).getUTCDay() + 6) % 7
  const cells: (string | null)[] = Array<null>(offset).fill(null)
  for (let day = first; day.startsWith(month); day = addDays(day, 1)) cells.push(day)
  while (cells.length % 7) cells.push(null)
  return Array.from({ length: cells.length / 7 }, (_, week) => cells.slice(week * 7, week * 7 + 7))
}

export const monthEnd = (month: string) => addDays(`${addMonths(month, 1)}-01`, -1)

export function monthTitle(month: string): string {
  const text = new Intl.DateTimeFormat('ru-RU', {
    month: 'long',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(new Date(`${month}-01T00:00:00Z`))
  return text.charAt(0).toUpperCase() + text.slice(1)
}
