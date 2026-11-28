import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { expect, it, vi } from 'vitest'

import { type Task, todayIso } from '../../lib/tasks'
import ClientCalendar from './ClientCalendar'

const task = (id: number, kind: Task['kind'], title: string) =>
  ({
    id,
    title,
    kind,
    company_name: 'ООО «Ромашка»',
    status: 'planned',
    due_date: todayIso(),
    amount_kopecks: null,
    client_note: '',
    can_mark_paid: false,
    can_unmark_paid: false,
  }) as Task

it('показывает платежи и документы подряд по датам, различая их подписью', async () => {
  const items = [task(2, 'notice', 'Уведомление об авансе'), task(1, 'payment', 'Налог')]
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) =>
      new Response(
        url.startsWith('/api/companies')
          ? '[{"id":1,"name":"ООО"}]'
          : JSON.stringify({ items, total: 2, today: todayIso() }),
      ),
    ),
  )
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <ClientCalendar />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  await screen.findByText('Налог')
  // один список по датам, как прислал сервер; тип виден по подписи
  expect(
    within(screen.getByRole('list'))
      .getAllByRole('listitem')
      .map((item) => item.textContent),
  ).toEqual([
    expect.stringContaining('Уведомление об авансе'),
    expect.stringContaining('Налог'),
  ])
  screen.getByText('К оплате')
  screen.getByText('Сдать уведомление')
})
