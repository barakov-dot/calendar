import { useEffect, useState } from 'react'

import { telegramDarkTheme } from './telegram'

export type ThemeChoice = 'system' | 'light' | 'dark'

const KEY = 'buh.theme'
const query = () => window.matchMedia?.('(prefers-color-scheme: dark)')

export function storedTheme(): ThemeChoice {
  const value = localStorage.getItem(KEY)
  return value === 'light' || value === 'dark' ? value : 'system'
}

/** «Как в системе» внутри Telegram означает тему самого Telegram. */
export function isDark(choice: ThemeChoice): boolean {
  if (choice !== 'system') return choice === 'dark'
  return telegramDarkTheme() ?? query()?.matches ?? false
}

export function applyTheme(choice: ThemeChoice = storedTheme()) {
  document.documentElement.classList.toggle('dark', isDark(choice))
}

export function useTheme() {
  const [theme, setTheme] = useState(storedTheme)

  useEffect(() => {
    applyTheme(theme)
    const media = query()
    const follow = () => applyTheme(theme)
    media?.addEventListener('change', follow)
    return () => media?.removeEventListener('change', follow)
  }, [theme])

  const choose = (choice: ThemeChoice) => {
    if (choice === 'system') localStorage.removeItem(KEY)
    else localStorage.setItem(KEY, choice)
    setTheme(choice)
  }
  return [theme, choose] as const
}
