import { plural } from './tasks'

/** Часовые пояса России: те же, что принимает сервер. */
export const TIME_ZONES: [string, string][] = [
  ['Europe/Kaliningrad', 'Калининград'],
  ['Europe/Moscow', 'Москва'],
  ['Europe/Samara', 'Самара (МСК+1)'],
  ['Asia/Yekaterinburg', 'Екатеринбург (МСК+2)'],
  ['Asia/Omsk', 'Омск (МСК+3)'],
  ['Asia/Krasnoyarsk', 'Красноярск (МСК+4)'],
  ['Asia/Irkutsk', 'Иркутск (МСК+5)'],
  ['Asia/Yakutsk', 'Якутск (МСК+6)'],
  ['Asia/Vladivostok', 'Владивосток (МСК+7)'],
  ['Asia/Magadan', 'Магадан (МСК+8)'],
  ['Asia/Kamchatka', 'Камчатка (МСК+9)'],
]

/** С 06:00 до 22:00 через полчаса; своё нестандартное время тоже остаётся в списке. */
export function timeOptions(current: string): string[] {
  const list = Array.from({ length: 33 }, (_, index) => {
    const minutes = 6 * 60 + index * 30
    const two = (value: number) => String(value).padStart(2, '0')
    return `${two(Math.floor(minutes / 60))}:${two(minutes % 60)}`
  })
  return list.includes(current) ? list : [...list, current].sort()
}

const daysWord = (count: number) => plural(count, ['день', 'дня', 'дней'])

export const offsetTitle = (days: number) => `за ${days} ${daysWord(days)}`

/** «за 7 и 1 день, в день срока». */
export function offsetsSummary(days: number[], onDueDay: boolean): string {
  const sorted = [...days].sort((a, b) => b - a)
  const parts: string[] = []
  if (sorted.length > 0) {
    const last = sorted[sorted.length - 1]
    const head = sorted.slice(0, -1).join(', ')
    parts.push(`за ${head ? `${head} и ` : ''}${last} ${daysWord(last)}`)
  }
  if (onDueDay) parts.push('в день срока')
  return parts.join(', ') || 'не напоминать'
}
