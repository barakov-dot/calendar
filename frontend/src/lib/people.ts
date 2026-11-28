import type { Role } from './types'

export interface Person {
  id: number
  first_name: string
  last_name: string
  username: string
  role: Role
  is_active: boolean
  connected: boolean
  bot_blocked: boolean
  companies_count: number
}

export interface PersonCard extends Person {
  telegram_id: number
  pd_consent_at: string | null
  created_at: string
  name_overridden: boolean
  /** Логин для входа на сайт по коду. */
  login: string | null
  companies: {
    id: number
    name: string
    is_archived: boolean
    is_primary: boolean | null
    can_mark_paid: boolean | null
    receive_reminders: boolean | null
  }[]
  substitutions: {
    id: number
    accountant_name: string
    substitute_name: string
    date_from: string
    date_to: string
  }[]
}

/** Почему пользователю не придут сообщения бота; пустой список — всё в порядке. */
export const personProblems = (person: Person) =>
  [
    !person.is_active && 'доступ отключён',
    !person.connected && 'не подключён к боту',
    person.bot_blocked && 'заблокировал(а) бота',
  ].filter((item): item is string => !!item)
