import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import TelegramTab from './TelegramTab'

const saved = {
  bot_username: '',
  mini_app_url: '',
  login_widget: false,
  proxy: {
    type: 'socks5' as const,
    enabled: false,
    host: '',
    port: 1080,
    username: '',
    password: '••••',
    has_password: true,
    rdns: true,
  },
}

function setup(checkOk: boolean) {
  const requests: { url: string; body: unknown }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init: RequestInit) => {
      requests.push({ url, body: init.body ? JSON.parse(String(init.body)) : null })
      const data = url.endsWith('test-proxy')
        ? { ok: checkOk, message: checkOk ? 'Бот доступен' : 'Нет соединения с прокси' }
        : url.endsWith('bot-status')
          ? { state: 'unknown' }
          : { settings: { telegram: saved }, file_error: null }
      return new Response(JSON.stringify(data))
    }),
  )
  render(
    <QueryClientProvider client={new QueryClient()}>
      <TelegramTab saved={saved} />
    </QueryClientProvider>,
  )
  return { requests, user: userEvent.setup() }
}

const saveButton = () => screen.getByRole<HTMLButtonElement>('button', { name: 'Сохранить' })

describe('настройки прокси', () => {
  it('разрешает сохранить только после успешной проверки тех же значений', async () => {
    const { requests, user } = setup(true)
    expect(saveButton().disabled).toBe(true)

    await user.type(screen.getByLabelText('Хост'), 'proxy.example')
    expect(saveButton().disabled).toBe(true)

    await user.click(screen.getByRole('button', { name: 'Проверить подключение' }))
    await screen.findByText(/Бот доступен/)
    expect(saveButton().disabled).toBe(false)

    await user.type(screen.getByLabelText('Хост'), '2')
    expect(saveButton().disabled).toBe(true)
    expect(screen.queryByText(/Бот доступен/)).toBeNull()
    expect(requests.some((request) => request.url === '/api/admin/settings')).toBe(false)
  })

  it('после неудачной проверки сохраняет только с подтверждением', async () => {
    const { requests, user } = setup(false)
    await user.type(screen.getByLabelText('Хост'), 'proxy.example')
    await user.click(screen.getByRole('button', { name: 'Проверить подключение' }))
    await screen.findByText(/Нет соединения с прокси/)
    expect(saveButton().disabled).toBe(true)
    const anyway = screen.getByRole('button', { name: 'Сохранить без проверки' })
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const saves = () => requests.filter((request) => request.url === '/api/admin/settings')

    await user.click(anyway)
    expect(saves()).toHaveLength(0)

    confirm.mockReturnValue(true)
    await user.click(anyway)
    await vi.waitFor(() => expect(saves()).toHaveLength(1))
    // пустой пароль уходит пустым: сервер сохранит прежний
    expect(saves()[0].body).toMatchObject({
      settings: { telegram: { proxy: { host: 'proxy.example', password: '' } } },
    })
  })
})
