import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'

import type { Role, User } from '../lib/types'
import Layout from './Layout'

function setup(role: Role) {
  const companies = [
    { id: 1, has_missing_amount: true, has_blocked_member: false },
    { id: 2, has_missing_amount: false, has_blocked_member: false },
  ]
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) =>
      new Response(
        JSON.stringify(url === '/api/demands' ? [{ closed: false }, { closed: true }] : companies),
      ),
    ),
  )
  const user: User = { id: 1, first_name: 'А', last_name: '', username: '', role, is_active: true }
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <Layout user={user} onLogout={() => {}} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return () => within(screen.getByRole('navigation', { name: 'Нижнее меню' }))
}

const titles = (links: HTMLElement[]) => links.map((link) => link.textContent)

describe('меню', () => {
  it('на телефоне вместо организаций — требования, организации в «Настройках»', async () => {
    const menu = setup('accountant')

    await menu().findByLabelText('открытых требований: 1')
    await menu().findByLabelText('требуют внимания: 1')
    expect(titles(menu().getAllByRole('link'))).toEqual([
      'Задачи',
      'Календарь',
      'Мои дела',
      '1Требования',
      '1Настройки',
    ])
    // в меню широкого экрана организации остаются
    const side = within(screen.getByRole('navigation', { name: 'Разделы' }))
    side.getByRole('link', { name: /Организации/ })
  })

  it('у помощника нет личных дел', () => {
    const menu = setup('assistant')

    expect(menu().queryByRole('link', { name: 'Мои дела' })).toBeNull()
  })

  it('у клиента свои кнопки внизу, без рабочих разделов', () => {
    const menu = setup('client')

    expect(titles(menu().getAllByRole('link'))).toEqual([
      'Платежи',
      'Календарь',
      'История',
      'Требования',
      'Настройки',
    ])
  })
})
