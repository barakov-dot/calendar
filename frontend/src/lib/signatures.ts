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
