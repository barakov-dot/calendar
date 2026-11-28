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

it('разделяет платежи и документы, которые не нужно оплачивать', async () => {
  const items = [task(1, 'payment', 'Налог'), task(2, 'notice', 'Уведомление об авансе')]
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
  const card = async (name: string) =>
    within((await screen.findByRole('heading', { name })).parentElement!)

  const payments = await card('Платежи')
  const documents = await card('Уведомления и отчёты')

  payments.getByText('Налог')
  payments.getByText('К оплате')
  expect(payments.queryByText('Уведомление об авансе')).toBeNull()
  documents.getByText('Уведомление об авансе')
  documents.getByText('Сдать уведомление')
})
