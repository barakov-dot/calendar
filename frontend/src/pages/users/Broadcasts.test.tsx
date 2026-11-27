import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'

import Broadcasts from './Broadcasts'

function setup(path = '/broadcasts') {
  const posts: { url: string; body: unknown }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init: RequestInit) => {
      if (init.method === 'POST') posts.push({ url, body: JSON.parse(init.body as string) })
      if (url.endsWith('/preview')) {
        return new Response(
          JSON.stringify({
            recipients: ['Пётр', 'Анна'],
            unreachable: [{ id: 3, name: 'Олег', reason: 'заблокировал(а) бота' }],
          }),
        )
      }
      return new Response(init.method === 'POST' ? '{}' : '[]')
    }),
  )
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={[path]}>
        <Broadcasts />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  const sent = () => posts.filter((call) => call.url === '/api/admin/broadcasts')
  return { posts, sent, user: userEvent.setup() }
}

const button = () => screen.getByRole<HTMLButtonElement>('button', { name: 'Отправить' })

describe('рассылка', () => {
  it('показывает получателей и отправляет только после подтверждения', async () => {
    const confirm = vi.fn(() => false)
    vi.stubGlobal('confirm', confirm)
    const { sent, user } = setup()
    expect(button().disabled).toBe(true)

    await user.click(screen.getByLabelText('Клиентам'))
    await screen.findByText('Получателей: 2')
    screen.getByText(/Олег — заблокировал/)
    await user.type(screen.getByLabelText(/Сообщение/), 'Офис закрыт')
    await user.click(button())
    expect(confirm).toHaveBeenCalledWith('Отправить сообщение? Получателей: 2.')
    expect(sent()).toHaveLength(0)

    confirm.mockReturnValue(true)
    await user.click(button())

    await waitFor(() => expect(sent()).toHaveLength(1))
    expect(sent()[0].body).toEqual({ roles: ['client'], user_ids: [], text: 'Офис закрыт' })
  })

  it('берёт отмеченных пользователей из адреса', async () => {
    const { posts } = setup('/broadcasts?users=4,7,мусор')

    await screen.findByText('Отмечены по одному: 2')
    await waitFor(() => expect(posts[0].body).toEqual({ roles: [], user_ids: [4, 7] }))
  })
})
