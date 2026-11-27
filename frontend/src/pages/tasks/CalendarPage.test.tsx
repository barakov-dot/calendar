import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { User } from '../../lib/types'
import CalendarPage from './CalendarPage'

const task = {
  id: 1,
  company_name: 'ООО «Ромашка»',
  kind: 'report',
  title: 'РСВ за 9 месяцев 2026',
  due_date: '2026-11-30',
  amount_kopecks: null,
  status: 'planned',
}

describe('календарь', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-11-27T09:00:00Z'))
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('показывает сетку месяца и задачи выбранного дня', async () => {
    const fetch = vi.fn(async (url: string) =>
      url.startsWith('/api/tasks?')
        ? new Response(JSON.stringify({ items: [task], total: 1, today: '2026-11-27' }))
        : new Response('[]'),
    )
    vi.stubGlobal('fetch', fetch)
    const user: User = {
      id: 1,
      first_name: 'А',
      last_name: '',
      username: '',
      role: 'accountant',
      is_active: true,
    }
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <CalendarPage user={user} />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    screen.getByText('Ноябрь 2026 г.')
    await userEvent.setup().click(await screen.findByLabelText('30.11.2026: задач 1'))
    screen.getByText('РСВ за 9 месяцев 2026')
    expect(fetch.mock.calls.some(([url]) => url.includes('from=2026-11-01&to=2026-11-30'))).toBe(
      true,
    )
  })
})
