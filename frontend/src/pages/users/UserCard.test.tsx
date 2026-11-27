import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { describe, expect, it, vi } from 'vitest'

import type { PersonCard } from '../../lib/people'
import UserCard from './UserCard'

const card: PersonCard = {
  id: 4,
  first_name: 'Пётр',
  last_name: '',
  username: 'petr',
  role: 'client',
  is_active: true,
  connected: true,
  bot_blocked: false,
  companies_count: 1,
  telegram_id: 100500,
  pd_consent_at: '2026-11-27T09:00:00Z',
  created_at: '2026-11-27T09:00:00Z',
  name_overridden: false,
  companies: [
    {
      id: 9,
      name: 'ООО «Ромашка»',
      is_archived: false,
      is_primary: true,
      can_mark_paid: false,
      receive_reminders: true,
    },
  ],
  substitutions: [],
}

function setup() {
  const patches: { url: string; body: unknown }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init: RequestInit) => {
      if (init.method === 'PATCH') patches.push({ url, body: JSON.parse(init.body as string) })
      return new Response(JSON.stringify(card))
    }),
  )
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={['/users/4']}>
        <Routes>
          <Route path="users/:id" element={<UserCard />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { patches, user: userEvent.setup() }
}

describe('карточка пользователя', () => {
  it('сохраняет новое имя', async () => {
    const { patches, user } = setup()

    await user.type(await screen.findByLabelText('Фамилия'), 'Смирнов')
    await user.click(screen.getByRole('button', { name: 'Сохранить имя' }))

    await waitFor(() =>
      expect(patches).toEqual([
        { url: '/api/admin/users/4', body: { first_name: 'Пётр', last_name: 'Смирнов' } },
      ]),
    )
  })

  it('меняет права клиента в организации', async () => {
    const { patches, user } = setup()

    await user.click(await screen.findByLabelText('Клиент платит сам'))

    await waitFor(() =>
      expect(patches).toEqual([
        { url: '/api/companies/9/members/4', body: { can_mark_paid: true } },
      ]),
    )
  })
})
