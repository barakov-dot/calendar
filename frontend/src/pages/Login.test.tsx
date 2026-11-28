import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { session } from '../lib/api'
import Login from './Login'

function setup(verify: () => Response) {
  const sent: { url: string; body: unknown }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init: RequestInit) => {
      if (init.method === 'POST') sent.push({ url, body: JSON.parse(String(init.body)) })
      if (url === '/api/auth/code-request') {
        return new Response(JSON.stringify({ request_id: 'abc' }))
      }
      if (url === '/api/auth/code-verify') return verify()
      return new Response(JSON.stringify({ widget_bot: null }))
    }),
  )
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <Login />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { sent, user: userEvent.setup() }
}

describe('вход по коду', () => {
  afterEach(() => {
    cleanup()
    session.clear()
  })

  it('запрашивает код по логину и входит с ним', async () => {
    const tokens = { access_token: 'a', refresh_token: 'r' }
    const { sent, user } = setup(() => new Response(JSON.stringify(tokens)))

    await user.type(screen.getByLabelText('Логин или @username'), 'ivanova{Enter}')
    // из кода берутся только цифры
    await user.type(await screen.findByLabelText('Код из Telegram'), '12 34-56{Enter}')

    await waitFor(() => expect(session.get()).toMatchObject(tokens))
    expect(sent).toEqual([
      { url: '/api/auth/code-request', body: { login: 'ivanova' } },
      { url: '/api/auth/code-verify', body: { request_id: 'abc', code: '123456' } },
    ])
  })

  it('показывает отказ и даёт начать заново', async () => {
    const { user } = setup(
      () => new Response(JSON.stringify({ detail: 'Неверный или просроченный код' }), { status: 422 }),
    )
    await user.type(screen.getByLabelText('Логин или @username'), '@anna{Enter}')
    await user.type(await screen.findByLabelText('Код из Telegram'), '000000{Enter}')

    await screen.findByText('Неверный или просроченный код')
    await user.click(screen.getByRole('button', { name: 'Назад' }))
    screen.getByLabelText('Логин или @username')
  })
})
