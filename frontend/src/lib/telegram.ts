import { postEvent, retrieveRawInitData } from '@telegram-apps/sdk-react'

/** initData, если приложение открыто внутри Telegram. */
export function miniAppInitData(): string | null {
  try {
    return retrieveRawInitData() || null
  } catch {
    return null // обычный браузер
  }
}

/** Убирает заставку Telegram и разворачивает окно приложения. */
export function announceMiniAppReady(): void {
  try {
    postEvent('web_app_ready')
    postEvent('web_app_expand')
  } catch {
    // старый клиент Telegram: приложение работает и без этого
  }
}
