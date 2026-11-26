import type { TaskKind } from './tasks'

export type Frequency = 'monthly' | 'quarterly' | 'yearly' | 'weekly'

export interface Schedule {
  frequency: Frequency
  day_of_month: number | null
  interval_weeks: number | null
}

export interface ReminderData {
  company_id: number | null
  title: string
  description: string
  kind: TaskKind
  schedule: Schedule
  dtstart: string
  until: string | null
  shift_rule: 'none' | 'next_workday' | 'prev_workday'
  audience: 'accountant' | 'client' | 'both'
  is_active: boolean
}

export interface Reminder extends ReminderData {
  id: number
  company_name: string
  created_by_name: string
  next_dates: string[]
  editable: boolean
}

export const FREQUENCY_NAMES: Record<Frequency, string> = {
  monthly: 'Ежемесячно',
  quarterly: 'Раз в квартал',
  yearly: 'Раз в год',
  weekly: 'Каждые N недель',
}

export const SHIFT_NAMES: Record<ReminderData['shift_rule'], string> = {
  next_workday: 'на следующий рабочий день',
  prev_workday: 'на предыдущий рабочий день',
  none: 'не переносить',
}

export const AUDIENCE_NAMES: Record<ReminderData['audience'], string> = {
  accountant: 'Только бухгалтеру',
  client: 'Клиенту',
  both: 'Бухгалтеру и клиенту',
}

export function describeSchedule(schedule: Schedule): string {
  if (schedule.frequency === 'weekly') return `каждые ${schedule.interval_weeks} нед.`
  return `${FREQUENCY_NAMES[schedule.frequency].toLowerCase()}, ${schedule.day_of_month}-го числа`
}

/** Только поля, которые принимает сервер. */
export function toData(reminder: Reminder): ReminderData {
  const { company_id, title, description, kind, schedule, dtstart, until } = reminder
  const { shift_rule, audience, is_active } = reminder
  return {
    company_id,
    title,
    description,
    kind,
    schedule,
    dtstart,
    until,
    shift_rule,
    audience,
    is_active,
  }
}
