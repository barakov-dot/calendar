import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'

import type { User } from '../../lib/types'
import NewCompany from './NewCompany'

const user: User = {
  id: 7,
  first_name: 'Б',
  last_name: '',
  username: '',
  role: 'accountant',
  is_active: true,
}

const party = {
  inn: '7707083893',
  kpp: '773601001',
  ogrn: '1027700132195',
  name: 'ПУБЛИЧНОЕ АКЦИОНЕРНОЕ ОБЩЕСТВО «ТЕСТ»',
  short_name: 'ПАО «Тест»',
  address: 'Москва',
  okved: '64.19',
  director_name: 'Директор',
  entity_type: 'ooo',
  region_code: '77',
  status: 'LIQUIDATING',
}

function setup(suggest: unknown) {
  const posts: unknown[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (_url: string, init: RequestInit) => {
      if (init.method === 'POST') {
        posts.push(JSON.parse(String(init.body)))
        return new Response(JSON.stringify({ id: 1 }))
      }
      return new Response(JSON.stringify(suggest))
    }),
  )
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <NewCompany user={user} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { posts, actions: userEvent.setup() }
}

describe('мастер добавления компании', () => {
  it('заполняет карточку из подсказки и создаёт компанию', async () => {
    const { posts, actions } = setup({ enabled: true, suggestions: [party] })

    await actions.type(screen.getByLabelText('ИНН или название'), '7707083893')
    await actions.click(await screen.findByRole('button', { name: /ПАО «Тест»/ }))

    expect(screen.getByText('Организация в процессе ликвидации.')).toBeTruthy()
    await actions.selectOptions(screen.getByLabelText('Режим налогообложения'), 'osno')
    await actions.click(screen.getByRole('button', { name: 'Создать компанию' }))

    await vi.waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0]).toMatchObject({
      accountant_id: 7,
      patents: [],
      company: { inn: '7707083893', main_regime: 'osno', nds_payer: true, region_code: '77' },
    })
    expect((posts[0] as { company: object }).company).not.toHaveProperty('status')
  })

  it('предлагает ручной ввод, когда DaData выключена', async () => {
    const { actions } = setup({ enabled: false, suggestions: [] })

    await actions.type(screen.getByLabelText('ИНН или название'), 'Ромашка')
    await screen.findByText(/DaData выключена/)
    await actions.click(screen.getByRole('button', { name: 'Заполнить вручную' }))

    expect(screen.getByLabelText(/^ИНН/)).toBeTruthy()
  })
})
