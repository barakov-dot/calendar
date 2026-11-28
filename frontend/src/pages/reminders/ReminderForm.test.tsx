import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { addDays, todayIso } from '../../lib/tasks'
import ReminderForm from './ReminderForm'

describe('форма напоминания', () => {
  afterEach(cleanup)

  async function setup() {
    const onSubmit = vi.fn()
    render(<ReminderForm companyId={1} onSubmit={onSubmit} onCancel={() => {}} />)
    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Название'), 'Аренда')
    const save = () => user.click(screen.getByRole('button', { name: 'Сохранить напоминание' }))
    return { onSubmit, user, save }
  }

  it('по умолчанию бессрочное: поля окончания нет', async () => {
    const { onSubmit, save } = await setup()

    expect(screen.queryByLabelText('Действует до')).toBeNull()
    await save()

    expect(onSubmit.mock.calls[0][0].until).toBeNull()
  })

  it('позволяет указать срок и вернуть бессрочность', async () => {
    const { onSubmit, user, save } = await setup()
    const endless = screen.getByLabelText('Бессрочно (без даты окончания)')

    await user.click(endless)
    const field = screen.getByLabelText('Действует до') as HTMLInputElement
    expect(field.value).toBe(addDays(todayIso(), 365))
    await user.clear(field)
    await save()
    expect(onSubmit).not.toHaveBeenCalled()

    await user.click(endless) // поле очищено — галочка осталась снятой, ставим снова
    await save()

    expect(onSubmit.mock.calls[0][0].until).toBeNull()
  })
})
