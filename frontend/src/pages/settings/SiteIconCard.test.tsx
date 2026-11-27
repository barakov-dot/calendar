import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import SiteIconCard from './SiteIconCard'

describe('иконка сайта', () => {
  it('загружает файл и обновляет значок вкладки', async () => {
    const link = document.createElement('link')
    link.rel = 'icon'
    link.dataset.siteIcon = ''
    link.href = '/api/site-icon'
    document.head.append(link)
    const sent: { url: string; method: string; body: unknown }[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init: RequestInit) => {
        sent.push({ url, method: String(init.method), body: init.body })
        return new Response(JSON.stringify({ content_type: 'image/png' }))
      }),
    )
    render(
      <QueryClientProvider client={new QueryClient()}>
        <SiteIconCard />
      </QueryClientProvider>,
    )
    // пока иконки нет, картинка не грузится
    fireEvent.error(screen.getByRole('img'))
    screen.getByText('Иконка не загружена.')

    await userEvent.upload(
      screen.getByLabelText('Загрузить иконку'),
      new File(['png'], 'icon.png', { type: 'image/png' }),
    )

    await screen.findByRole('img')
    expect(sent[0]).toMatchObject({ url: '/api/admin/site-icon', method: 'POST' })
    expect(sent[0].body).toBeInstanceOf(File)
    await waitFor(() => expect(link.href).toContain('/api/site-icon?v='))
    link.remove()
  })
})
