import { describe, expect, it, vi } from 'vitest'

import { api, session } from './api'

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status })

describe('api', () => {
  it('обновляет токен один раз для параллельных запросов и повторяет их', async () => {
    session.set({ access_token: 'old', refresh_token: 'r' })
    const fetchMock = vi.fn(async (url: string, init: RequestInit) => {
      if (url === '/api/auth/refresh') {
        return json(200, { access_token: 'new', refresh_token: 'r2' })
      }
      const header = (init.headers as Record<string, string>).Authorization
      return header === 'Bearer new' ? json(200, { ok: url }) : json(401, { detail: 'нет' })
    })
    vi.stubGlobal('fetch', fetchMock)

    const results = await Promise.all([api('/a'), api('/b')])

    expect(results).toEqual([{ ok: '/api/a' }, { ok: '/api/b' }])
    expect(fetchMock.mock.calls.filter(([url]) => url === '/api/auth/refresh')).toHaveLength(1)
    expect(session.get()?.refresh_token).toBe('r2')
  })

  it('выходит, если обновить токен нельзя', async () => {
    session.set({ access_token: 'old', refresh_token: 'r' })
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => json(401, { detail: 'Требуется вход' })),
    )

    await expect(api('/me')).rejects.toMatchObject({ status: 401 })
    expect(session.get()).toBeNull()
  })

  it('передаёт текст ошибки сервера и сообщает об отсутствии связи', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => json(403, { detail: 'Доступ по приглашению' })),
    )
    await expect(api('/x')).rejects.toThrow('Доступ по приглашению')

    vi.stubGlobal(
      'fetch',
      vi.fn(async () => Promise.reject(new TypeError('offline'))),
    )
    await expect(api('/x')).rejects.toMatchObject({ status: 0 })
  })
})
