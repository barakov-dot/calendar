import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
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
  is_payment: false,
  no_response: false,
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
    no_response: false,
  },
  {
    knd: '',
    name: 'Другой документ инспекции',
    action: 'Исполнить',
    response_label: 'Срок исполнения',
    response_workdays: null,
    is_payment: false,
    no_response: false,
  },
]

const people = [
  { user_id: 3, name: 'Клиент', group: 'client', reason: null, status: null, sent_at: null },
  {
    user_id: 4,
    name: 'Дина',
    group: 'assistant',
    reason: 'заблокировал(а) бота',
    status: null,
    sent_at: null,
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
        '/api/demands/7/recipients': people,
        '/api/demands/7/share': people,
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
    // посчитанные даты стоят прямо в полях
    const value = (label: string) => (screen.getByLabelText(label, { exact: false }) as HTMLInputElement).value
    expect(value('Дата получения требования')).toBe('2026-11-27')
    expect(value('Дата квитанции о приёме')).toBe('2026-12-07')
    expect(screen.getByDisplayValue('2026-12-14')).toBeTruthy()
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

  it('дату исполнения можно заменить и снова посчитать', async () => {
    const { calls, user } = setup('/demands')
    await user.click(await screen.findByRole('button', { name: 'Добавить без файла' }))
    fireEvent.change(screen.getByLabelText('Дата документа'), {
      target: { value: '2026-11-27' },
    })
    const due = await screen.findByDisplayValue('2026-12-14')

    fireEvent.change(due, { target: { value: '2026-12-18' } })

    await screen.findByText(/Задано вручную/)
    await waitFor(() =>
      expect(calls.at(-1)).toMatchObject({
        url: '/api/demands/dates',
        body: { response_date: '2026-12-18', receipt_date: null },
      }),
    )
    await user.click(screen.getByRole('button', { name: 'Посчитать заново' }))
    expect(screen.queryByText(/Задано вручную/)).toBeNull()
  })

  it('удалить может только администратор', async () => {
    setup('/demands/7')
    await screen.findByRole('button', { name: 'Изменить' })
    expect(screen.queryByRole('button', { name: 'Удалить' })).toBeNull()
    cleanup()

    setup('/demands/7', 'admin')
    await screen.findByRole('button', { name: 'Удалить' })
  })

  it('отправляет требование отмеченным получателям', async () => {
    const { calls, user } = setup('/demands/7')

    await user.click(await screen.findByLabelText('Клиент'))
    expect(screen.getByLabelText('Дина')).toHaveProperty('disabled', true)
    await user.type(screen.getByLabelText('Сообщение получателям'), 'Посмотрите')
    await user.click(screen.getByRole('button', { name: /Отправить в Telegram/ }))

    await waitFor(() =>
      expect(calls.find((call) => call.url === '/api/demands/7/share')?.body).toEqual({
        user_ids: [3],
        comment: 'Посмотрите',
      }),
    )
  })

  it('клиент видит требование без задач и кнопок', async () => {
    const hidden = {
      ...demand,
      filename: 'a.pdf',
      content_type: 'application/pdf',
      receipt: { ...demand.receipt!, task_id: null },
      response: { ...demand.response!, task_id: null },
    }
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify(hidden))),
    )
    const user: User = {
      id: 2,
      first_name: 'К',
      last_name: '',
      username: '',
      role: 'client',
      is_active: true,
    }
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={['/demands/7']}>
          <Routes>
            <Route path="/demands/:id" element={<DemandPage user={user} />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )

    await screen.findByRole('button', { name: 'Открыть' })
    screen.getByText('Представить пояснения')
    expect(screen.queryByRole('link', { name: 'Представить пояснения' })).toBeNull()
    expect(screen.queryByRole('link', { name: 'ООО «Пример»' })).toBeNull()
    for (const name of ['Квитанция подписана', 'Изменить', 'Удалить']) {
      expect(screen.queryByRole('button', { name })).toBeNull()
    }
    expect(screen.queryByText('Приложить файл')).toBeNull()
  })

  it('помощник видит список, но не загружает и не отмечает', async () => {
    setup('/demands', 'assistant')

    await screen.findByText(/пояснений № 100/)
    expect(screen.queryByLabelText('Загрузить требование')).toBeNull()
  })
})
