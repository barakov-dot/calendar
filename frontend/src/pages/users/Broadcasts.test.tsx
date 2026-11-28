import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
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
    expect(sent()[0].body).toEqual({
      roles: ['client'],
      user_ids: [],
      company_ids: [],
      company_groups: [],
      text: 'Офис закрыт',
    })
  })

  it('берёт отмеченных пользователей из адреса', async () => {
    const { posts } = setup('/broadcasts?users=4,7,мусор')

    await screen.findByText('Отмечены по одному: 2')
    await waitFor(() =>
      expect(posts[0].body).toMatchObject({ roles: [], user_ids: [4, 7], company_ids: [] }),
    )
  })

  it('отправляет по организациям, по умолчанию клиентам', async () => {
    cleanup()
    const posts: { url: string; body: unknown }[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init: RequestInit) => {
        if (init.method === 'POST') posts.push({ url, body: JSON.parse(init.body as string) })
        if (url.startsWith('/api/companies')) {
          return new Response('[{"id":5,"name":"ООО Ромашка","short_name":"","inn":"1"}]')
        }
        if (url.endsWith('/preview')) {
          return new Response(JSON.stringify({ recipients: ['Пётр'], unreachable: [] }))
        }
        return new Response('[]')
      }),
    )
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <Broadcasts />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    const user = userEvent.setup()

    await user.click(screen.getByText('По организациям'))
    await user.click(await screen.findByLabelText('ООО Ромашка'))

    await screen.findByText('Получателей: 1')
    expect(posts.at(-1)?.body).toMatchObject({ company_ids: [5], company_groups: ['client'] })
  })

  it('убирает в архив и удаляет только после подтверждения', async () => {
    cleanup()
    const calls: string[] = []
    const item = {
      id: 9,
      text: 'Старое сообщение',
      roles: ['client'],
      company_names: [],
      company_groups: [],
      archived: false,
      author_name: 'А',
      created_at: '2026-11-01T10:00:00Z',
      total: 1,
      sent: 1,
      pending: 0,
      failed: 0,
      skipped: 0,
    }
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init: RequestInit) => {
        if (init.method !== 'GET') calls.push(`${init.method} ${url}`)
        if (init.method !== 'GET') return new Response(null, { status: 204 })
        return new Response(JSON.stringify(url === '/api/admin/broadcasts' ? [item] : []))
      }),
    )
    const confirm = vi.fn(() => false)
    vi.stubGlobal('confirm', confirm)
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <Broadcasts />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: 'Удалить' }))
    expect(calls).toEqual([])
    await user.click(screen.getByRole('button', { name: 'В архив' }))
    await waitFor(() => expect(calls).toEqual(['POST /api/admin/broadcasts/archive']))
    confirm.mockReturnValue(true)
    await user.click(screen.getByRole('button', { name: 'Удалить' }))
    await waitFor(() => expect(calls.at(-1)).toBe('DELETE /api/admin/broadcasts/9'))
  })
})
