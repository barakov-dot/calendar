import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import RosstatBlock, { type RosstatData } from './RosstatBlock'

const data: RosstatData = {
  enabled: true,
  okpo: '12345678',
  checked_at: '2026-11-28T00:00:00Z',
  error: '',
  forms: [
    {
      id: 1,
      index: 'П-4',
      name: 'Сведения о численности',
      okud: '0606010',
      periodicity: 'Месячная',
      period: 'за ноябрь 2026',
      deadline: '15.12.2026',
      comment: '',
      task_id: 9,
      status: 'planned',
    },
  ],
}

function setup(editable: boolean) {
  const sent: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init: RequestInit) => {
      sent.push(`${init.method} ${url}`)
      return new Response(JSON.stringify(data))
    }),
  )
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <RosstatBlock companyId={3} editable={editable} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { sent, user: userEvent.setup() }
}

describe('формы Росстата в карточке', () => {
  afterEach(cleanup)

  it('показывает формы со сроками и ищет по кнопке', async () => {
    const { sent, user } = setup(true)

    await screen.findByText('15.12.2026')
    screen.getByText('Сведения о численности')
    screen.getByRole('link', { name: 'Открыть задачу' })
    await user.click(screen.getByRole('button', { name: 'Проверить сейчас' }))

    await waitFor(() => expect(sent).toContain('POST /api/companies/3/rosstat/refresh'))
  })

  it('помощнику не даёт запускать поиск', async () => {
    setup(false)

    await screen.findByText('15.12.2026')
    expect(screen.queryByRole('button', { name: 'Проверить сейчас' })).toBeNull()
  })
})
