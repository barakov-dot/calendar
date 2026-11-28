import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { expect, it, vi } from 'vitest'

import type { User } from '../../lib/types'
import type { Report, ReportRow, Result } from './report'
import Reports from './Reports'

const row = (task_id: number, company_id: number, result: Result, title: string): ReportRow => ({
  task_id,
  company_id,
  result,
  accountant: 'Анна',
  company: company_id === 1 ? 'Первая' : 'Вторая',
  title,
  kind: 'Отчёт',
  due: '2026-10-26',
  status: result === 'overdue' ? 'Не отмечено' : 'Сдано',
  marked: result === 'overdue' ? null : '2026-10-20',
  marked_by: '',
  timing: result === 'overdue' ? 'Просрочено' : 'В срок',
  amount_kopecks: null,
})

const total = (company_id: number, company: string, on_time: number, overdue: number) => ({
  company_id,
  company,
  accountant: 'Анна',
  on_time,
  late: 0,
  not_required: 0,
  overdue,
  paid_kopecks: 0,
})

const report: Report = {
  tasks: 3,
  summary: [total(1, 'Первая', 1, 1), total(2, 'Вторая', 0, 1)],
  rows: [
    row(11, 1, 'on_time', 'Сданный отчёт'),
    row(12, 1, 'overdue', 'Пропущенный первой'),
    row(21, 2, 'overdue', 'Пропущенный второй'),
  ],
}

it('по нажатию на цифру показывает именно эти задачи', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async (url: string) => new Response(JSON.stringify(url.includes('/reports/') ? report : [])),
    ),
  )
  const viewer: User = {
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
        <Reports user={viewer} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  const user = userEvent.setup()
  const titles = () =>
    within(screen.getByRole('list'))
      .getAllByRole('link')
      .map((link) => link.textContent)

  await user.click(await screen.findByRole('button', { name: 'Первая: просрочено — 1, показать' }))
  expect(titles()).toEqual(['Пропущенный первой'])
  screen.getByRole('heading', { name: 'Задачи: Первая' })

  await user.click(screen.getByRole('button', { name: 'В срок · 1' }))
  expect(titles()).toEqual(['Сданный отчёт'])

  await user.click(screen.getByRole('button', { name: 'Всего: просрочено — 2, показать' }))
  expect(titles()).toEqual(['Пропущенный первой', 'Пропущенный второй'])
  expect(screen.getByRole('link', { name: 'Пропущенный второй' }).getAttribute('href')).toBe(
    '/tasks/21',
  )
})
