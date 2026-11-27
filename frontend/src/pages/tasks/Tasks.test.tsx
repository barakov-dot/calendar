import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { Task } from '../../lib/tasks'
import type { Role, User } from '../../lib/types'
import Tasks from './Tasks'

const task = (id: number, due_date: string, extra: Partial<Task> = {}): Task => ({
  id,
  company_id: 1,
  company_name: 'ООО «Ромашка»',
  kind: 'report',
  title: `Задача ${id}`,
  due_date,
  amount_kopecks: null,
  status: 'planned',
  client_note: '',
  source_ref: '',
  source: 'rule',
  needs_amount: false,
  can_mark_paid: false,
  can_unmark_paid: false,
  ...extra,
})

const late = task(1, '2026-11-25', {
  action_title: 'Подать уведомление по НДФЛ',
  period_label: 'за 1–22 ноября 2026',
})
const payment = task(2, '2026-11-30', { kind: 'payment', action_title: 'Уплатить НДФЛ' })
const later = task(3, '2026-12-20')

function setup(role: Role = 'accountant') {
  const bulk: { ids: number[]; status: string }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init: RequestInit) => {
      if (url === '/api/tasks/bulk') {
        bulk.push(JSON.parse(init.body as string))
        return new Response(JSON.stringify({ updated: 1, skipped: 0 }))
      }
      if (url.startsWith('/api/tasks?')) {
        const overdue = new URL(url, 'http://x').searchParams.has('to')
        const to = new URL(url, 'http://x').searchParams.get('to')!
        const items = overdue && to < '2026-11-27' ? [late] : [payment, later]
        return new Response(
          JSON.stringify({ items, total: items.length, today: '2026-11-27' }),
        )
      }
      return new Response('[]')
    }),
  )
  const user: User = {
    id: 5,
    first_name: 'Анна',
    last_name: '',
    username: '',
    role,
    is_active: true,
  }
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <Tasks user={user} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { bulk, user: userEvent.setup() }
}

const tab = (name: RegExp) => screen.getByRole('tab', { name })

describe('экран задач', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-11-27T09:00:00Z'))
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('считает задачи по периодам и показывает прошедшие сроки отдельно', async () => {
    const { user } = setup()

    await screen.findByText('На неделе 1 задача')
    screen.getByText(/1 срок уже прошёл/)
    expect(tab(/Сегодня/).textContent).toBe('Сегодня1')
    expect(tab(/Неделя/).textContent).toBe('Неделя2')
    expect(tab(/Месяц/).textContent).toBe('Месяц3')
    await screen.findByText('Подать уведомление по НДФЛ')
    screen.getByText('за 1–22 ноября 2026 · ООО «Ромашка»')
    screen.getByText('2 дня назад')
    screen.getByText('Пн, 30 ноября')
    expect(screen.queryByText('Задача 3')).toBeNull()

    await user.click(tab(/Месяц/))
    await screen.findByText('Задача 3')
  })

  it('отмечает задачу одним нажатием и позволяет отменить', async () => {
    const { bulk, user } = setup()

    await user.click(await screen.findByRole('checkbox', { name: /Оплачено.*Задача 2/ }))

    await waitFor(() => expect(bulk).toEqual([{ ids: [2], status: 'paid' }]))
    await user.click(await screen.findByRole('button', { name: 'Отменить' }))
    await waitFor(() => expect(bulk[1]).toEqual({ ids: [2], status: 'planned' }))
  })

  it('«Отметить все» после подтверждения закрывает прошедшие сроки', async () => {
    vi.stubGlobal('confirm', vi.fn(() => true))
    const { bulk, user } = setup()

    await user.click(await screen.findByRole('button', { name: 'Отметить все' }))

    await waitFor(() => expect(bulk).toEqual([{ ids: [1], status: 'done' }]))
  })

  it('помощнику не даёт отмечать и добавлять', async () => {
    setup('assistant')

    const row = await screen.findByText('Уплатить НДФЛ')
    expect(within(document.body).queryByRole('checkbox')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Отметить все' })).toBeNull()
    expect(screen.queryByRole('link', { name: 'Добавить задачу' })).toBeNull()
    expect(row).toBeTruthy()
  })
})
