import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import Declarations, { type Declaration } from './Declarations'

const found: Declaration = {
  company_id: 1,
  company_name: 'ООО «Пример»',
  inn: '0000000000',
  year: 2026,
  quarter: 3,
  correction: 1,
  total_kopecks: 30_000_00,
  warnings: ['Есть раздел 2 (налоговый агент).'],
  parts: [
    {
      task_id: 1,
      part: 1,
      due_date: '2026-10-28',
      current_kopecks: 500_00,
      new_kopecks: 10_000_00,
      kept: 'уже оплачен',
    },
    {
      task_id: 2,
      part: 2,
      due_date: '2026-11-30',
      current_kopecks: null,
      new_kopecks: 10_000_00,
      kept: '',
    },
  ],
}

function setup(reply: () => Response) {
  const calls: { url: string; body: unknown }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init: RequestInit) => {
      calls.push({ url, body: init.body })
      return reply()
    }),
  )
  render(
    // как в приложении: без повторов
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <Declarations />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { calls, user: userEvent.setup() }
}

const file = () => new File(['<Файл/>'], 'NO_NDS.xml', { type: 'text/xml' })
const choose = (user: ReturnType<typeof userEvent.setup>) =>
  user.upload(screen.getByLabelText(/Перетащите XML/), file())

describe('загрузка декларации', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('показывает изменения и записывает суммы только по кнопке', async () => {
    const { calls, user } = setup(() => new Response(JSON.stringify(found)))

    await choose(user)

    await screen.findByText('ООО «Пример»')
    screen.getByText(/III квартал 2026, корректировка № 1/)
    screen.getByText(/Не меняется: уже оплачен/)
    screen.getByText('Есть раздел 2 (налоговый агент).')
    expect(calls.map((call) => call.url)).toEqual(['/api/declarations/preview'])
    expect(calls[0].body).toBeInstanceOf(File)

    await user.click(screen.getByRole('button', { name: 'Вписать суммы' }))

    await screen.findByText('Суммы записаны. Платежей изменено: 1.')
    expect(calls[1].url).toBe('/api/declarations/apply')
    expect(screen.queryByRole('button', { name: 'Вписать суммы' })).toBeNull()
  })

  it('объясняет, почему файл не подошёл', async () => {
    const detail = 'Организации с ИНН 0000000000 нет среди ваших'
    const { user } = setup(() => new Response(JSON.stringify({ detail }), { status: 422 }))

    await choose(user)

    await screen.findByText(detail)
    expect(screen.queryByRole('button', { name: 'Вписать суммы' })).toBeNull()
  })
})
