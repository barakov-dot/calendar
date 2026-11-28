/** «Должность — ФИО» одной строкой: так владелец подписи хранится и показывается. */
const SEPARATOR = ' — '

/** Выбор «другое»: владельца вписывают вручную. */
export const OTHER = ''

export interface Holder {
  /** Название из списка или OTHER. */
  role: string
  /** ФИО к названию из списка, а для OTHER — весь текст. */
  name: string
}

export function splitHolder(holder: string, roles: string[]): Holder {
  if (!holder) return { role: roles[0] ?? OTHER, name: '' }
  for (const role of roles) {
    if (holder === role) return { role, name: '' }
    if (holder.startsWith(role + SEPARATOR)) {
      return { role, name: holder.slice(role.length + SEPARATOR.length) }
    }
  }
  return { role: OTHER, name: holder }
}

export function joinHolder({ role, name }: Holder): string {
  const text = name.trim()
  if (role === OTHER) return text
  return text ? role + SEPARATOR + text : role
}

export type Urgency = 'ok' | 'soon' | 'urgent'

/** Больше 30 дней — спокойно, от 7 до 30 — пора заняться, меньше 7 (и истёкшие) — срочно. */
export function urgencyOf(daysLeft: number): Urgency {
  if (daysLeft > 30) return 'ok'
  return daysLeft >= 7 ? 'soon' : 'urgent'
}

export const URGENCY_STYLES: Record<Urgency, string> = {
  ok: 'bg-green-100 text-green-900 dark:bg-green-950 dark:text-green-200',
  soon: 'bg-yellow-100 text-yellow-900 dark:bg-yellow-950 dark:text-yellow-200',
  urgent: 'bg-red-100 text-red-900 dark:bg-red-950 dark:text-red-200',
}
