import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { isOverdue, type Task, toneOf } from '../../lib/tasks'
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
const filed = task(4, '2026-10-26', { status: 'done', action_title: 'Сдать декларацию по НДС' })
const asked: string[] = []

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
        const query = new URL(url, 'http://x').searchParams
        if (query.get('status') === 'done') {
          asked.push(url)
          return new Response(
            JSON.stringify({ items: [filed], total: 1, today: '2026-11-27' }),
          )
        }
        const overdue = query.has('to')
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

  it('открывается на ближайшую неделю, прошедшие сроки спрятаны', async () => {
    const { user } = setup()

    await screen.findByText('На неделе 1 задача')
    await screen.findByText(/1 срок уже прошёл/)
    expect(tab(/Неделя/).getAttribute('aria-selected')).toBe('true')
    expect(tab(/Сегодня/).textContent).toBe('Сегодня0')
    expect(tab(/Неделя/).textContent).toBe('Неделя1')
    expect(tab(/Месяц/).textContent).toBe('Месяц2')
    screen.getByText('Пн, 30 ноября')
    expect(screen.queryByText('Подать уведомление по НДФЛ')).toBeNull()
    expect(screen.queryByText('Задача 3')).toBeNull()

    await user.click(tab(/Месяц/))
    await screen.findByText('Задача 3')
  })

  it('сданные отчёты открываются отдельной кнопкой и не зачёркнуты', async () => {
    const { bulk, user } = setup()
    expect(screen.queryByText('Сдать декларацию по НДС')).toBeNull()

    await user.click(await screen.findByRole('button', { name: /Сданные отчёты1/ }))

    const row = await screen.findByText('Сдать декларацию по НДС')
    expect(row.className).not.toContain('line-through')
    expect(screen.queryByText('Уплатить НДФЛ')).toBeNull()
    const query = new URL(asked[0], 'http://x').searchParams
    expect(query.getAll('kind')).toEqual(['report', 'notice'])
    expect(query.get('newest_first')).toBe('true')
    await user.click(screen.getByRole('checkbox', { name: /Вернуть в план/ }))
    await waitFor(() => expect(bulk).toEqual([{ ids: [4], status: 'planned' }]))

    await user.click(screen.getByRole('button', { name: '← К задачам' }))
    await screen.findByText('Уплатить НДФЛ')
  })

  it('помощник видит у сданного отчёта зелёную галочку', async () => {
    const { user } = setup('assistant')

    await user.click(await screen.findByRole('button', { name: /Сданные отчёты/ }))

    await screen.findByRole('img', { name: 'Сдано' })
  })

  it('не считает пропущенными сроки до начала ведения календаря', () => {
    const old = task(9, '2026-10-01', { before_start: true })

    expect(toneOf(old, '2026-11-27')).toBe('history')
    expect(isOverdue(old, '2026-11-27')).toBe(false)
    expect(isOverdue({ ...old, before_start: false }, '2026-11-27')).toBe(true)
    expect(toneOf({ ...old, status: 'paid' }, '2026-11-27')).toBe('closed')
  })

  it('показывает и снова прячет прошедшие сроки по нажатию', async () => {
    const { user } = setup()

    await user.click(await screen.findByRole('button', { name: 'Показать' }))

    await screen.findByText('Подать уведомление по НДФЛ')
    screen.getByText('за 1–22 ноября 2026 · ООО «Ромашка»')
    screen.getByText('2 дня назад')
    await user.click(screen.getByRole('button', { name: 'Скрыть' }))
    expect(screen.queryByText('Подать уведомление по НДФЛ')).toBeNull()
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

    await user.click(await screen.findByRole('button', { name: 'Показать' }))
    await user.click(await screen.findByRole('button', { name: 'Отметить все' }))

    await waitFor(() => expect(bulk).toEqual([{ ids: [1], status: 'done' }]))
  })

  it('помощнику не даёт отмечать и добавлять', async () => {
    const { user } = setup('assistant')

    await user.click(await screen.findByRole('button', { name: 'Показать' }))
    const row = await screen.findByText('Уплатить НДФЛ')
    expect(within(document.body).queryByRole('checkbox')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Отметить все' })).toBeNull()
    expect(screen.queryByRole('link', { name: 'Добавить задачу' })).toBeNull()
    expect(row).toBeTruthy()
  })
})
