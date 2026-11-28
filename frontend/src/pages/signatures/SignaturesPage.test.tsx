import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import SignaturesPage, { type SignatureRow } from './SignaturesPage'

const row = (id: number, company_name: string, expires_on: string, days_left: number) => ({
  id,
  company_id: id,
  company_name,
  holder: 'Генеральный директор',
  expires_on,
  days_left,
})

const rows: SignatureRow[] = [
  row(1, 'Вега', '2026-12-01', 3),
  row(2, 'Альфа', '2027-06-01', 185),
  row(3, 'Бета', '2026-12-20', 22),
]

const names = () =>
  screen.getAllByRole('link').map((link) => within(link).getByText(/Вега|Альфа|Бета/).textContent)

describe('раздел ЭЦП', () => {
  afterEach(cleanup)

  it('сортирует по сроку и названию и подсвечивает сроки', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify(rows))),
    )
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <SignaturesPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    const user = userEvent.setup()

    await screen.findByText('Вега')
    expect(names()).toEqual(['Вега', 'Бета', 'Альфа'])
    expect(screen.getByText(/до 01.12.2026/).className).toContain('bg-red')
    expect(screen.getByText(/до 20.12.2026/).className).toContain('bg-yellow')
    expect(screen.getByText(/до 01.06.2027/).className).toContain('bg-green')

    await user.click(screen.getByRole('button', { name: /По названию/ }))
    expect(names()).toEqual(['Альфа', 'Бета', 'Вега'])
    await user.click(screen.getByRole('button', { name: /По названию/ }))
    expect(names()).toEqual(['Вега', 'Бета', 'Альфа'])
    await user.click(screen.getByRole('button', { name: /По сроку/ }))
    expect(names()).toEqual(['Вега', 'Бета', 'Альфа'])

    await user.type(screen.getByLabelText(/Поиск/), 'альф')
    expect(names()).toEqual(['Альфа'])
  })
})
