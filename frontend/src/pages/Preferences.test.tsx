import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { offsetsSummary, timeOptions } from '../lib/reminderTimes'
import type { User } from '../lib/types'
import PreferencesPage from './Preferences'

const saved = {
  offsets_days: [7, 1],
  on_due_day: true,
  daily_digest: true,
  digest_time: null,
  timezone: null,
  defaults: {
    offsets_days: [7, 3, 1],
    on_due_day: true,
    digest_time: '09:00',
    timezone: 'Europe/Moscow',
  },
}

function setup() {
  const bodies: unknown[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init: RequestInit) => {
      if (url.endsWith('/contacts')) {
        return new Response(JSON.stringify({ support_contact: '', accountants: [] }))
      }
      if (init.method === 'PUT') {
        const body = JSON.parse(String(init.body))
        bodies.push(body)
        return new Response(JSON.stringify({ ...saved, ...body }))
      }
      return new Response(JSON.stringify(saved))
    }),
  )
  const user: User = {
    id: 1,
    first_name: 'К',
    last_name: '',
    username: '',
    role: 'client',
    is_active: true,
  }
  render(
    <QueryClientProvider client={new QueryClient()}>
      <PreferencesPage user={user} onLogout={() => {}} />
    </QueryClientProvider>,
  )
  return { bodies, actions: userEvent.setup() }
}

describe('настройки напоминаний клиента', () => {
  afterEach(cleanup)

  it('сохраняет отмеченные дни, своё число, время и пояс', async () => {
    const { bodies, actions } = setup()
    await screen.findByText('за 7 и 1 день, в день срока')
    const box = (name: string) => screen.getByRole('checkbox', { name }) as HTMLInputElement
    expect([box('за 14 дней').checked, box('за 7 дней').checked]).toEqual([false, true])

    await actions.click(box('за 7 дней'))
    await actions.click(screen.getByRole('button', { name: 'Изменить «за 3 дня»' }))
    const field = screen.getByLabelText('За сколько дней')
    await actions.clear(field)
    await actions.type(field, '5{Enter}')
    await actions.selectOptions(screen.getByLabelText('Время'), '08:30')
    await actions.selectOptions(screen.getByLabelText('Часовой пояс'), 'Asia/Omsk')
    screen.getByText('за 5 и 1 день, в день срока')
    await actions.click(screen.getByRole('button', { name: 'Сохранить' }))

    await screen.findByText('Сохранено.')
    expect(bodies[0]).toMatchObject({
      offsets_days: [1, 5],
      on_due_day: true,
      digest_time: '08:30',
      timezone: 'Asia/Omsk',
    })
  })

  it('не меняет то, что оставлено по умолчанию', async () => {
    const { bodies, actions } = setup()
    await actions.click(await screen.findByRole('checkbox', { name: 'В день срока' }))
    await actions.click(screen.getByRole('button', { name: 'Сохранить' }))

    await vi.waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0]).toMatchObject({
      offsets_days: [7, 1],
      on_due_day: false,
      digest_time: null,
      timezone: null,
    })
  })

  it.each([
    [[1, 14, 3], false, 'за 14, 3 и 1 день'],
    [[2], false, 'за 2 дня'],
    [[], true, 'в день срока'],
    [[], false, 'не напоминать'],
  ])('подпись %j', (days, onDueDay, text) => {
    expect(offsetsSummary(days, onDueDay)).toBe(text)
  })

  it('в списке времени есть и нестандартное', () => {
    expect(timeOptions('09:15')).toContain('09:15')
    expect(timeOptions('09:00').at(0)).toBe('06:00')
    expect(timeOptions('09:00').at(-1)).toBe('22:00')
  })
})
