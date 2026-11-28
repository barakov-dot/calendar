import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { expect, it, vi } from 'vitest'

import type { User } from '../../lib/types'
import CompaniesList from './CompaniesList'

const company = (id: number, name: string, extra: object = {}) => ({
  id,
  inn: '0000000000',
  name,
  short_name: '',
  entity_type: 'ooo',
  main_regime: 'usn6',
  accountant_name: '',
  patents_count: 0,
  members_count: 0,
  has_missing_amount: false,
  has_blocked_member: false,
  has_signature: true,
  ...extra,
})

it('отмечает кружком только организации, посчитанные в меню', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async () =>
        new Response(
          JSON.stringify([
            company(1, 'Спокойная'),
            company(2, 'Без суммы', { has_missing_amount: true }),
            company(3, 'Заблокировал', { has_blocked_member: true }),
          ]),
        ),
    ),
  )
  const user: User = {
    id: 1,
    first_name: 'А',
    last_name: '',
    username: '',
    role: 'admin',
    is_active: true,
  }
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <CompaniesList user={user} />
      </MemoryRouter>
    </QueryClientProvider>,
  )

  const card = async (name: string) =>
    within((await screen.findByText(name)).closest('a')!)
  expect((await card('Спокойная')).queryByRole('img')).toBeNull()
  ;(await card('Без суммы')).getByRole('img', { name: /есть задачи без суммы/ })
  ;(await card('Заблокировал')).getByRole('img', { name: /клиент заблокировал бота/ })
  screen.getByRole('heading', { name: 'Организации · 3' })
  ;(await card('Спокойная')).getByText('1')
  ;(await card('Заблокировал')).getByText('3')
})
