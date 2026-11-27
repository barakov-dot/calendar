/**
 * Ссылки, открывающие приложение Telegram напрямую. Сайт t.me открывается не у всех,
 * а приложение работает и через прокси.
 */
export interface TelegramTarget {
  /** Для браузера: открывает приложение, минуя сайт. */
  href: string
  /** Путь для Mini App: Telegram открывает его сам. */
  path: string
}

/** Чат с ботом или человеком по ссылке вида https://t.me/имя?start=… */
export function chatTarget(link: string): TelegramTarget {
  const { pathname, search, searchParams } = new URL(link)
  const name = pathname.slice(1)
  const start = searchParams.get('start')
  const href = `tg://resolve?domain=${encodeURIComponent(name)}`
  return {
    href: start ? `${href}&start=${encodeURIComponent(start)}` : href,
    path: pathname + search,
  }
}

export const userTarget = (username: string) =>
  chatTarget(`https://t.me/${encodeURIComponent(username)}`)

/** Выбор чата, в который отправить ссылку с пояснением. */
export function shareTarget(link: string, text: string): TelegramTarget {
  const query = `url=${encodeURIComponent(link)}&text=${encodeURIComponent(text)}`
  return { href: `tg://msg_url?${query}`, path: `/share/url?${query}` }
}
