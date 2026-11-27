import { afterEach, describe, expect, it, vi } from 'vitest'

import { showBackButton } from './telegram'

type Receiver = { receiveEvent: (name: string, data?: unknown) => void }

describe('стрелка «Назад» Telegram', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('просит клиент показать стрелку, слушает нажатие и убирает за собой', () => {
    const sent: [string, unknown][] = []
    // так приложения Telegram принимают события от Mini App
    vi.stubGlobal('TelegramWebviewProxy', {
      postEvent: (name: string, data: string) => sent.push([name, JSON.parse(data)]),
    })
    const press = vi.fn()

    const hide = showBackButton(press)
    // приёмник событий есть, только пока кто-то их слушает
    const client = () => (window as unknown as { TelegramGameProxy?: Receiver }).TelegramGameProxy
    client()?.receiveEvent('back_button_pressed')
    hide()
    client()?.receiveEvent?.('back_button_pressed')

    expect(press).toHaveBeenCalledOnce()
    expect(sent).toEqual([
      ['web_app_setup_back_button', { is_visible: true }],
      ['web_app_setup_back_button', { is_visible: false }],
    ])
  })
})
