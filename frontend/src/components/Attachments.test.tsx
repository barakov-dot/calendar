import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import Attachments, { type AttachmentList } from './Attachments'

const item = {
  id: 7,
  filename: 'платёжка.pdf',
  content_type: 'image/png',
  size: 2048,
  uploaded_by_name: 'Пётр',
  created_at: '2026-11-27T09:00:00Z',
  can_delete: false,
}

function setup(list: Partial<AttachmentList>) {
  const sent: { url: string; init: RequestInit }[] = []
  const fetch = vi.fn(async (url: string, init: RequestInit) => {
    if (init.method !== 'GET') sent.push({ url, init })
    const data = { items: [], can_upload: false, max_bytes: 100, ...list }
    return new Response(JSON.stringify(data))
  })
  vi.stubGlobal('fetch', fetch)
  const view = render(
    <QueryClientProvider client={new QueryClient()}>
      <Attachments taskId={5} />
    </QueryClientProvider>,
  )
  return { ...view, sent, fetch, user: userEvent.setup() }
}

const field = () => screen.findByLabelText<HTMLInputElement>(/Перетащите файл/)

describe('файлы к платежу', () => {
  it('отправляет файл телом запроса, а имя — в заголовке', async () => {
    const { sent, user } = setup({ can_upload: true })
    const file = new File(['%PDF-'], 'Платёжка 1.pdf', { type: 'application/pdf' })

    await user.upload(await field(), file)

    await waitFor(() => expect(sent).toHaveLength(1))
    expect(sent[0].url).toBe('/api/tasks/5/attachments')
    expect(sent[0].init.body).toBe(file)
    expect(sent[0].init.headers).toMatchObject({
      'X-Filename': encodeURIComponent('Платёжка 1.pdf'),
    })
  })

  it('не отправляет слишком большой файл', async () => {
    const { sent, user } = setup({ can_upload: true })

    await user.upload(await field(), new File(['0'.repeat(101)], 'x.pdf', { type: 'application/pdf' }))

    await screen.findByText('Файл больше 10 МБ: x.pdf')
    expect(sent).toHaveLength(0)
  })

  it('без права загрузки и без файлов не показывается', async () => {
    const { container, fetch } = setup({})

    await waitFor(() => expect(fetch).toHaveBeenCalled())
    await waitFor(() => expect(container.textContent).toBe(''))
  })

  it('без права удаления показывает только получение файла', async () => {
    setup({ items: [item] })

    await screen.findByText('платёжка.pdf')
    expect(screen.getByRole('button', { name: 'Прислать в Telegram' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Удалить' })).toBeNull()
    expect(screen.queryByLabelText(/Перетащите файл/)).toBeNull()
  })

  it('принимает перетащенные файлы и отправляет их по очереди', async () => {
    const { sent } = setup({ can_upload: true })
    const files = [new File(['%PDF-'], 'a.pdf'), new File(['%PDF-'], 'b.pdf')]
    const zone = (await field()).closest('label')!

    fireEvent.dragOver(zone)
    screen.getByText('Отпустите файл здесь')
    fireEvent.drop(zone, { dataTransfer: { files } })

    await waitFor(() => expect(sent).toHaveLength(2))
    expect(sent.map((call) => call.init.body)).toEqual(files)
  })

  it('по нажатию на имя открывает файл на странице и закрывает по Escape', async () => {
    URL.createObjectURL = vi.fn(() => 'blob:preview')
    URL.revokeObjectURL = vi.fn()
    const { fetch, user } = setup({ items: [item] })

    await user.click(await screen.findByText('платёжка.pdf'))

    const picture = await screen.findByRole('img', { name: 'платёжка.pdf' })
    expect(picture.getAttribute('src')).toBe('blob:preview')
    expect(fetch.mock.calls.some(([url]) => url === '/api/attachments/7')).toBe(true)

    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:preview')
  })
})
