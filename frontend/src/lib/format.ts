const dateTime = new Intl.DateTimeFormat('ru-RU', {
  timeZone: 'Europe/Moscow',
  dateStyle: 'medium',
  timeStyle: 'short',
})

/** Дата и время по Москве. Принимает ISO-строку или секунды Unix. */
export function formatDateTime(value: string | number): string {
  return dateTime.format(new Date(typeof value === 'number' ? value * 1000 : value))
}

/** «7, 3, 1» → [7, 3, 1]; null, если строка не список дней от 1 до 365. */
export function parseOffsets(text: string): number[] | null {
  const parts = text.split(/[\s,;]+/).filter(Boolean)
  const days = parts.map(Number)
  if (days.some((day) => !Number.isInteger(day) || day < 1 || day > 365)) return null
  return [...new Set(days)].sort((a, b) => b - a)
}

export function fullName(user: { first_name: string; last_name: string; username: string }) {
  const name = `${user.first_name} ${user.last_name}`.trim()
  return name || (user.username ? `@${user.username}` : 'Без имени')
}
