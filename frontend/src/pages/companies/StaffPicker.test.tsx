import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { StaffPicker } from './StaffPicker'

const staff = [
  { id: 1, name: 'Анна', role: 'accountant' },
  { id: 2, name: 'Борис', role: 'chief' },
  { id: 3, name: 'Дина', role: 'assistant' },
]

describe('выбор сотрудников организации', () => {
  afterEach(cleanup)

  it('отмечает нескольких и показывает отключённого из уже назначенных', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(staff))))
    const onChange = vi.fn()
    render(
      <QueryClientProvider client={new QueryClient()}>
        <StaffPicker
          value={{ accountant_ids: [1, 9], assistant_ids: [] }}
          onChange={onChange}
          current={{ accountants: [{ id: 9, name: 'Вера', is_active: false }], assistants: [] }}
        />
      </QueryClientProvider>,
    )
    const actions = userEvent.setup()

    await actions.click(await screen.findByLabelText('Борис'))
    expect(onChange).toHaveBeenLastCalledWith({ accountant_ids: [1, 9, 2], assistant_ids: [] })
    await actions.click(screen.getByLabelText('Вера (отключён)'))
    expect(onChange).toHaveBeenLastCalledWith({ accountant_ids: [1], assistant_ids: [] })
    await actions.click(screen.getByLabelText('Дина'))
    expect(onChange).toHaveBeenLastCalledWith({ accountant_ids: [1, 9], assistant_ids: [3] })
  })
})
