import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { Demand } from '../../lib/demands'
import type { Role, User } from '../../lib/types'
import DemandPage from './DemandPage'
import DemandsPage from './DemandsPage'

const demand: Demand = {
  id: 7,
  company_id: 1,
  company_name: 'ООО «Пример»',
  knd: '1165050',
  name: 'Требование о представлении пояснений',
  action: 'Представить пояснения',
  response_label: 'Срок исполнения',
  number: '100',
  doc_date: '2026-11-27',
  sent_date: '2026-11-27',
  receipt_date: '2026-12-07',
  receipt_set: false,
  response_workdays: 5,
  response_date: '2026-12-14',
  response_set: false,
  amount_kopecks: null,
  note: '',
  filename: '',
  content_type: '',
  closed: false,
  receipt: { task_id: 11, due_date: '2026-12-07', status: 'planned' },
  response: { task_id: 12, due_date: '2026-12-14', status: 'planned' },
}

const kinds = [
  {
    knd: '1165050',
    name: 'Требование о представлении пояснений',
    action: 'Представить пояснения',
    response_label: 'Срок исполнения',
    response_workdays: 5,
    is_payment: false,
  },
  {
    knd: '',
    name: 'Другой документ инспекции',
    action: 'Исполнить',
    response_label: 'Срок исполнения',
    response_workdays: null,
    is_payment: false,
  },
]

function setup(path: string, role: Role = 'accountant') {
  const calls: { url: string; method: string; body: unknown }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init: RequestInit) => {
      const json = typeof init.body === 'string' ? JSON.parse(init.body) : init.body
      calls.push({ url, method: String(init.method), body: json })
      const replies: Record<string, unknown> = {
        '/api/demands/types': kinds,
        '/api/demands/dates': { receipt_date: '2026-12-07', response_date: '2026-12-14' },
        '/api/demands/recognize': {
          readable: true,
          company_id: 1,
          inn: '0000000000',
          knd: '1165050',
          number: '100',
          doc_date: '2026-11-27',
          response_workdays: 5,
          response_date: null,
          amount_kopecks: null,
          note: '',
        },
        '/api/companies': [{ id: 1, name: 'ООО «Пример»', short_name: '' }],
        '/api/demands/7': demand,
        '/api/tasks/bulk': { updated: 1, skipped: 0 },
      }
      if (url === '/api/demands') {
        return new Response(JSON.stringify(init.method === 'POST' ? demand : [demand]))
      }
      return new Response(JSON.stringify(replies[url] ?? demand))
    }),
  )
  const user: User = { id: 1, first_name: 'А', last_name: '', username: '', role, is_active: true }
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/demands" element={<DemandsPage user={user} />} />
          <Route path="/demands/:id" element={<DemandPage user={user} />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { calls, user: userEvent.setup() }
}

describe('требования', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-11-27T09:00:00Z'))
  })
  afterEach(() => {
    cleanup()
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('распознаёт загруженный файл и сохраняет требование вместе с ним', async () => {
    const { calls, user } = setup('/demands')

    await user.upload(
      await screen.findByLabelText('Загрузить требование'),
      new File(['%PDF'], 'demand.pdf', { type: 'application/pdf' }),
    )

    await screen.findByText(/Проверьте распознанные данные/)
    await screen.findByText(/Квитанция — 07.12.2026. Срок исполнения — 14.12.2026./)
    const save = screen.getByRole('button', { name: 'Сохранить требование' })
    await waitFor(() => expect(save).toHaveProperty('disabled', false))
    await user.click(save)

    await screen.findByText('Подписать квитанцию о приёме')
    const created = calls.find((call) => call.url === '/api/demands' && call.method === 'POST')!
    expect(created.body).toMatchObject({
      company_id: 1,
      knd: '1165050',
      response_workdays: 5,
      receipt_date: null,
      response_date: null,
      receipt_done: false,
    })
    expect(calls.some((call) => call.url === '/api/demands/7/file')).toBe(true)
  })

  it('отмечает квитанцию подписанной', async () => {
    const { calls, user } = setup('/demands/7')

    await user.click(await screen.findByRole('button', { name: 'Квитанция подписана' }))

    await waitFor(() =>
      expect(calls.find((call) => call.url === '/api/tasks/bulk')?.body).toEqual({
        ids: [11],
        status: 'done',
      }),
    )
  })

  it('помощник видит список, но не загружает и не отмечает', async () => {
    setup('/demands', 'assistant')

    await screen.findByText(/пояснений № 100/)
    expect(screen.queryByLabelText('Загрузить требование')).toBeNull()
  })
})
