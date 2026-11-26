import { retrieveRawInitData } from '@telegram-apps/sdk-react'

/** initData, если приложение открыто внутри Telegram. */
export function miniAppInitData(): string | null {
  try {
    return retrieveRawInitData() || null
  } catch {
    return null // обычный браузер
  }
}
