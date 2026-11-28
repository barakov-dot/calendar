import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import SignaturesBlock from './SignaturesBlock'

const existing = {
  id: 4,
  holder: 'Менеджер — Петров П.П.',
  expires_on: '2027-03-01',
  notify_client: false,
  days_left: 90,
}

function setup(list: unknown[] = []) {
  const sent: { method: string; body: unknown }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init: RequestInit) => {
      if (init.method !== 'GET') {
        sent.push({ method: String(init.method), body: JSON.parse(String(init.body)) })
      }
      if (url === '/api/signature-holders') {
        return new Response(JSON.stringify(['Генеральный директор', 'Менеджер']))
      }
      return new Response(JSON.stringify(init.method === 'GET' ? list : existing))
    }),
  )
  render(
    <QueryClientProvider client={new QueryClient()}>
      <SignaturesBlock companyId={1} editable />
    </QueryClientProvider>,
  )
  return { sent, user: userEvent.setup() }
}

describe('подпись из списка', () => {
  afterEach(cleanup)

  it('генеральный директор выбран сразу, нужна только дата', async () => {
    const { sent, user } = setup()

    await user.click(await screen.findByRole('button', { name: 'Добавить подпись' }))
    const select = (await screen.findByLabelText('На кого выпущена')) as HTMLSelectElement
    expect(select.value).toBe('Генеральный директор')
    await user.type(screen.getByLabelText('Действует до'), '2027-05-20')
    await user.click(screen.getByRole('button', { name: 'Сохранить подпись' }))

    await waitFor(() =>
      expect(sent[0].body).toMatchObject({
        holder: 'Генеральный директор',
        expires_on: '2027-05-20',
      }),
    )
  })

  it('при изменении разбирает владельца и даёт вписать своего', async () => {
    const { sent, user } = setup([existing])

    await user.click(await screen.findByRole('button', { name: 'Изменить' }))
    const select = (await screen.findByLabelText('На кого выпущена')) as HTMLSelectElement
    expect(select.value).toBe('Менеджер')
    expect(screen.getByDisplayValue('Петров П.П.')).toBeTruthy()

    await user.selectOptions(select, 'Другое — вписать вручную')
    const name = screen.getByLabelText('Кто')
    await user.clear(name)
    await user.type(name, 'Юрист')
    await user.click(screen.getByRole('button', { name: 'Сохранить подпись' }))

    await waitFor(() => expect(sent[0].body).toMatchObject({ holder: 'Юрист' }))
  })
})
