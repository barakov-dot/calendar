import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { describe, expect, it, vi } from 'vitest'

import type { TaskDetail } from '../../lib/tasks'
import type { Role, User } from '../../lib/types'
import TaskPage from './TaskPage'

const task: TaskDetail = {
  id: 5,
  company_id: 1,
  company_name: 'ООО «Тест»',
  kind: 'payment',
  title: 'НДС: платёж 1 из 3',
  due_date: '2026-07-28',
  original_due_date: '2026-07-28',
  amount_kopecks: null,
  status: 'planned',
  client_note: '',
  comment: 'секрет',
  source: 'rule',
  source_ref: 'п. 1 ст. 174 НК РФ',
  needs_amount: true,
  rule_code: 'nds_payment',
  period_key: '2026-Q2',
  part: 1,
  description: '',
  due_overridden: false,
  amount_overridden: false,
  client_visible: true,
  status_changed_at: null,
  status_changed_by_name: '',
  status_changed_by_role: null,
  recurring_reminder_id: null,
  nds_parts: [1, 2, 3].map((part) => ({
    id: 4 + part,
    part,
    due_date: '2026-07-28',
    amount_kopecks: null,
    amount_overridden: false,
    status: 'planned' as const,
  })),
}

function setup(role: Role) {
  const sent: { url: string; method: string; body: unknown }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init: RequestInit) => {
      if (init.method !== 'GET') {
        sent.push({ url, method: String(init.method), body: JSON.parse(String(init.body)) })
        return new Response(JSON.stringify({ updated: 3, skipped: 0 }))
      }
      return new Response(JSON.stringify(task))
    }),
  )
  const user = { id: 1, role } as User
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={['/tasks/5']}>
        <Routes>
          <Route path="/tasks/:id" element={<TaskPage user={user} />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { sent, actions: userEvent.setup() }
}

describe('страница задачи', () => {
  it('отправляет только изменённые поля, сумму — в копейках', async () => {
    const { sent, actions } = setup('accountant')

    await actions.type(await screen.findByLabelText(/^Сумма, ₽/), '1 000,5')
    await actions.click(screen.getByRole('button', { name: 'Сохранить' }))

    await vi.waitFor(() => expect(sent).toHaveLength(1))
    expect(sent[0]).toMatchObject({ method: 'PATCH', url: '/api/tasks/5' })
    expect(sent[0].body).toEqual({ amount_kopecks: 100050 })
  })

  it('делит НДС за квартал и отмечает все части', async () => {
    const { sent, actions } = setup('admin')
    vi.spyOn(window, 'confirm').mockReturnValue(true)

    await actions.type(await screen.findByLabelText(/за весь квартал/), '100000')
    await actions.click(screen.getByRole('button', { name: 'Разделить на три платежа' }))
    await actions.click(screen.getByRole('button', { name: 'Отметить все части оплаченными' }))

    await vi.waitFor(() => expect(sent).toHaveLength(2))
    expect(sent[0]).toEqual({
      url: '/api/tasks/nds/1/2026-Q2',
      method: 'PUT',
      body: { amount_kopecks: 10000000 },
    })
    expect(sent[1].body).toEqual({ ids: [5, 6, 7], status: 'paid' })
  })

  it('помощнику показывает всё без возможности изменить', async () => {
    setup('assistant')

    await screen.findByText(/Внутренний комментарий: секрет/)
    expect(screen.queryByRole('button', { name: 'Оплачено' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Сохранить' })).toBeNull()
    expect(screen.queryByLabelText(/за весь квартал/)).toBeNull()
  })
})
