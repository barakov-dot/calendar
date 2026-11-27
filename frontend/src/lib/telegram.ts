import { on, postEvent, retrieveLaunchParams, retrieveRawInitData } from '@telegram-apps/sdk-react'

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

/**
 * Показывает стрелку «Назад» в шапке Mini App вместо «Закрыть».
 * Возвращает функцию, которая убирает стрелку.
 */
export function showBackButton(onPress: () => void): () => void {
  const visible = (is_visible: boolean) => {
    try {
      postEvent('web_app_setup_back_button', { is_visible })
    } catch {
      // старый клиент Telegram: кнопки нет
    }
  }
  try {
    const off = on('back_button_pressed', onPress)
    visible(true)
    return () => {
      off()
      visible(false)
    }
  } catch {
    return () => {}
  }
}

/** Открывает чат или выбор чата внутри Telegram: path — часть ссылки после t.me. */
export function openTelegramPath(path: string): void {
  try {
    postEvent('web_app_open_tg_link', { path_full: path as `/${string}` })
  } catch {
    // старый клиент Telegram: ссылку можно скопировать
  }
}

/** Тёмная ли тема у Telegram; null — приложение открыто не в Telegram. */
export function telegramDarkTheme(): boolean | null {
  try {
    const params = retrieveLaunchParams() as { tgWebAppThemeParams?: { bg_color?: string } }
    return isDarkColor(params.tgWebAppThemeParams?.bg_color)
  } catch {
    return null
  }
}

/** Тёмный ли цвет вида #rrggbb (по воспринимаемой яркости). */
export function isDarkColor(color: string | undefined): boolean | null {
  const match = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(color ?? '')
  if (!match) return null
  const [red, green, blue] = match.slice(1).map((part) => parseInt(part, 16))
  return 0.299 * red + 0.587 * green + 0.114 * blue < 128
}
