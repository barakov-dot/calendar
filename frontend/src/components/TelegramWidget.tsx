import { useMutation, useQuery } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'

import { api, session, type Tokens } from '../lib/api'
import { ErrorText } from './ui'

declare global {
  interface Window {
    onTelegramAuth?: (user: Record<string, unknown>) => void
  }
}

/** Кнопка входа от Telegram. Показывается, только если включена в настройках. */
export default function TelegramWidget() {
  const options = useQuery({
    queryKey: ['auth-options'],
    queryFn: () => api<{ widget_bot: string | null }>('/auth/options'),
  })
  const login = useMutation({
    mutationFn: (user: Record<string, unknown>) =>
      api<Tokens>('/auth/telegram-widget', { method: 'POST', body: user }),
    onSuccess: (tokens) => session.set(tokens),
  })
  const { mutate } = login
  const bot = options.data?.widget_bot
  const holder = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const element = holder.current
    if (!bot || !element) return
    window.onTelegramAuth = mutate
    // официальный скрипт Telegram сам рисует кнопку на своём месте
    const script = document.createElement('script')
    script.src = 'https://telegram.org/js/telegram-widget.js?22'
    script.async = true
    script.dataset.telegramLogin = bot
    script.dataset.size = 'large'
    script.dataset.onauth = 'onTelegramAuth(user)'
    element.appendChild(script)
    return () => {
      delete window.onTelegramAuth
      element.replaceChildren()
    }
  }, [bot, mutate])

  if (!bot) return null
  return (
    <div className="space-y-2 border-t border-slate-200 pt-3 dark:border-slate-700">
      <p className="text-sm text-slate-500 dark:text-slate-400">Или кнопкой Telegram:</p>
      <div ref={holder} />
      <ErrorText error={login.error} />
    </div>
  )
}
