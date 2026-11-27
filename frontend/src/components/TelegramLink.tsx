import type { MouseEvent, ReactNode } from 'react'

import { miniAppInitData, openTelegramPath } from '../lib/telegram'
import type { TelegramTarget } from '../lib/telegramLinks'

/** Ссылка в приложение Telegram: из браузера и из Mini App. */
export default function TelegramLink({
  to,
  className,
  children,
}: {
  to: TelegramTarget
  className?: string
  children: ReactNode
}) {
  const open = (event: MouseEvent) => {
    // из окна Mini App адреса tg:// не открываются
    if (!miniAppInitData()) return
    event.preventDefault()
    openTelegramPath(to.path)
  }
  return (
    <a href={to.href} onClick={open} className={className}>
      {children}
    </a>
  )
}
