import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'

import { addDays, clientStatus, type Task, todayIso } from '../../lib/tasks'
import ClientPayments from './ClientPayments'

const task = (id: number, extra: Partial<Task>) =>
  ({
    id,
    title: `Платёж ${id}`,
    company_name: 'ООО «Ромашка»',
    kind: 'payment',
    status: 'planned',
    due_date: addDays(todayIso(), 3),
    amount_kopecks: 3333334,
    client_note: '',
    can_mark_paid: false,
    can_unmark_paid: false,
    ...extra,
  }) as Task

function setup(items: Task[]) {
  const posts: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init: RequestInit) => {
      if (init.method === 'POST') {
        posts.push(url)
        return new Response('{}')
      }
      if (url.startsWith('/api/companies')) return new Response('[{"id":1,"name":"ООО"}]')
      const data = url.includes('status=planned') ? items : []
      return new Response(JSON.stringify({ items: data, total: data.length, today: todayIso() }))
    }),
  )
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <ClientPayments />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { posts, actions: userEvent.setup() }
}

describe('платежи клиента', () => {
  it('показывает сумму и срок; «Оплатил» — только где разрешено', async () => {
    const { posts, actions } = setup([
      task(1, { can_mark_paid: true }),
      task(2, { due_date: addDays(todayIso(), -1) }),
    ])
    vi.spyOn(window, 'confirm').mockReturnValue(true)

    await screen.findByText('Платёж 1')
    expect(screen.getAllByText(/33\s333,34\s₽/)).toHaveLength(2)
    const overdue = screen.getByRole('heading', { name: 'Срок прошёл' }).parentElement!
    expect(within(overdue).getByText('Платёж 2')).toBeTruthy()
    expect(screen.getAllByRole('button', { name: 'Оплатил' })).toHaveLength(1)

    await actions.click(screen.getByRole('button', { name: 'Оплатил' }))

    await vi.waitFor(() => expect(posts).toEqual(['/api/tasks/1/mark-paid']))
  })

  it('называет статусы по-клиентски', () => {
    expect(clientStatus({ kind: 'payment', status: 'planned' })).toBe('К оплате')
    expect(clientStatus({ kind: 'report', status: 'planned' })).toBe('Готовится')
    expect(clientStatus({ kind: 'report', status: 'done' })).toBe('Сдано ✓')
    expect(clientStatus({ kind: 'payment', status: 'paid' })).toBe('Оплачено ✓')
  })
})
