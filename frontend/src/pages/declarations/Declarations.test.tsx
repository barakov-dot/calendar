import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { blockedReason, type Declaration } from './batch'
import Declarations from './Declarations'

const found: Declaration = {
  company_id: 1,
  company_name: 'ООО «Пример»',
  inn: '0000000000',
  title: 'НДС за III квартал 2026',
  correction: 1,
  totals: [{ label: 'К уплате за квартал', kopecks: 30_000_00 }],
  warnings: ['Есть раздел 2 (налоговый агент).'],
  switches_to_monthly: false,
  enables: [],
  parts: [
    {
      task_id: 1,
      title: 'НДС: платёж 1 из 3',
      due_date: '2026-10-28',
      current_kopecks: 500_00,
      new_kopecks: 10_000_00,
      kept: 'уже оплачен',
    },
    {
      task_id: 2,
      title: 'НДС: платёж 2 из 3',
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
    screen.getByText('К уплате за квартал')
    screen.getByRole('link', { name: 'НДС: платёж 2 из 3' })
    screen.getByText(/Не меняется: уже оплачен/)
    screen.getByText('Есть раздел 2 (налоговый агент).')
    expect(calls.map((call) => call.url)).toEqual(['/api/declarations/preview'])
    expect(calls[0].body).toBeInstanceOf(File)

    await user.click(screen.getByRole('button', { name: 'Вписать суммы' }))

    await screen.findByText('Суммы записаны. Платежей изменено: 1.')
    expect(calls[1].url).toBe('/api/declarations/apply')
    expect(screen.queryByRole('button', { name: 'Вписать суммы' })).toBeNull()
  })

  it('предупреждает о переходе на ежемесячные авансы и не ведёт на несуществующий платёж', async () => {
    const reply = {
      ...found,
      switches_to_monthly: true,
      parts: [{ ...found.parts[1], task_id: null, title: 'Аванс за июль' }],
    }
    const { user } = setup(() => new Response(JSON.stringify(reply)))

    await choose(user)

    await screen.findByText(/При записи порядок изменится/)
    screen.getByText('Аванс за июль (новый)')
    expect(screen.queryByRole('link', { name: /Аванс за июль/ })).toBeNull()
  })

  it('предупреждает, что отметит налоги в карточке', async () => {
    const reply = { ...found, enables: ['Транспортный налог'] }
    const { user } = setup(() => new Response(JSON.stringify(reply)))

    await choose(user)

    await screen.findByText(/При записи в карточке организации будет отмечено: «Транспортный налог»/)
  })

  it('объясняет, почему файл не подошёл', async () => {
    const detail = 'Организации с ИНН 0000000000 нет среди ваших'
    const { user } = setup(() => new Response(JSON.stringify({ detail }), { status: 422 }))

    await choose(user)

    await screen.findByText(detail)
    expect(screen.queryByRole('button', { name: 'Вписать суммы' })).toBeNull()
  })

  it('записывает всю пачку одной кнопкой, корректировку после исходной, ошибки не мешают', async () => {
    const part = found.parts[1]
    const replies: Record<string, Declaration> = {
      'primary.xml': { ...found, correction: 0, parts: [part] },
      'fix.xml': { ...found, correction: 1, parts: [{ ...part, new_kopecks: 20_000_00 }] },
      'other.xml': { ...found, company_id: 2, company_name: 'ООО «Вторая»', parts: [part] },
    }
    const applied: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init: RequestInit) => {
        const name = (init.body as File).name
        if (url.endsWith('/apply')) applied.push(name)
        const reply = replies[name]
        return reply
          ? new Response(JSON.stringify(reply))
          : new Response(JSON.stringify({ detail: 'Это не декларация' }), { status: 422 })
      }),
    )
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <Declarations />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    const user = userEvent.setup()

    await user.upload(
      screen.getByLabelText(/Перетащите XML/),
      ['primary.xml', 'fix.xml', 'other.xml', 'bad.xml'].map(
        (name) => new File(['<Файл/>'], name, { type: 'text/xml' }),
      ),
    )

    await screen.findByText('bad.xml: Это не декларация')
    screen.getByText(/есть в более поздней корректировке \(«fix.xml»\)/)
    expect(applied).toEqual([])
    await user.click(screen.getByRole('button', { name: 'Вписать суммы из всех файлов (2)' }))

    await vi.waitFor(() => expect(document.querySelector('p[role=status]')?.textContent).toContain('Записано: 2'))
    // у обоих корректировка № 1: порядок — как выбирали
    expect(applied).toEqual(['fix.xml', 'other.xml'])
  })

  it('не записывает вместе файлы, которые спорят об одной сумме', () => {
    const item = (id: number, kopecks: number) => ({
      id,
      file: new File([''], `${id}.xml`),
      status: 'ready' as const,
      data: { ...found, parts: [{ ...found.parts[1], new_kopecks: kopecks }] },
    })
    const [first, second, same] = [item(1, 100), item(2, 200), item(3, 100)]

    expect(blockedReason(first, [first, second])).toMatch('2.xml')
    expect(blockedReason(second, [first, second])).toMatch('1.xml')
    expect(blockedReason(first, [first, same])).toBe('')
  })
})

