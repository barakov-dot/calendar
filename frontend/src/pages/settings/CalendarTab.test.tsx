import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'

import CalendarTab from './CalendarTab'

it('загружает файл года и отклоняет не-JSON', async () => {
  const posts: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init: RequestInit) => {
      if (init.method === 'POST') {
        posts.push(url)
        return new Response(JSON.stringify({ year: 2028, tasks_created: 1, tasks_updated: 2 }))
      }
      return new Response('[]')
    }),
  )
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  render(
    <QueryClientProvider client={new QueryClient()}>
      <CalendarTab />
    </QueryClientProvider>,
  )
  const user = userEvent.setup()
  const input = screen.getByLabelText('Загрузить файл на год (JSON)')
  await screen.findByText(/Календарь не загружен/)

  await user.upload(input, new File(['{'], 'bad.json', { type: 'application/json' }))
  await screen.findByText('Файл не является JSON')
  expect(posts).toHaveLength(0)

  await user.upload(input, new File(['{"year":2028}'], '2028.json', { type: 'application/json' }))
  await screen.findByText(/Календарь 2028 загружен/)
  expect(posts).toEqual(['/api/admin/calendar/2028'])
})
