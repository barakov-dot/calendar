import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'

import type { Task } from '../lib/tasks'
import TaskTable from './TaskTable'

const task = (id: number, title: string) =>
  ({
    id,
    title,
    company_name: 'ООО',
    kind: 'payment',
    status: 'planned',
    due_date: '2026-01-01',
    amount_kopecks: null,
    needs_amount: true,
  }) as Task

function setup(editable: boolean) {
  const sent: unknown[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (_url: string, init: RequestInit) => {
      sent.push(JSON.parse(String(init.body)))
      return new Response(JSON.stringify({ updated: 1, skipped: 1 }))
    }),
  )
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <TaskTable tasks={[task(1, 'Первая'), task(2, 'Вторая')]} today="2026-02-01" editable={editable} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { sent, actions: userEvent.setup() }
}

describe('список задач', () => {
  it('меняет статус выбранных после подтверждения', async () => {
    const { sent, actions } = setup(true)
    expect(screen.getAllByText('Просрочено')).toHaveLength(2)
    expect(screen.queryByRole('button', { name: 'Оплачено' })).toBeNull()
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)

    await actions.click(screen.getByLabelText('Выбрать: Вторая, ООО'))
    await actions.click(screen.getByRole('button', { name: 'Оплачено' }))
    expect(sent).toHaveLength(0)

    confirm.mockReturnValue(true)
    await actions.click(screen.getByRole('button', { name: 'Оплачено' }))
    await screen.findByText(/Пропущено \(статус не подходит\): 1/)
    expect(sent).toEqual([{ ids: [2], status: 'paid' }])
  })

  it('без права изменения нет выбора', () => {
    setup(false)

    expect(screen.queryByRole('checkbox')).toBeNull()
  })
})
