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

  it('передаёт сумму платежа в копейках и не принимает неверную', async () => {
    const { onSubmit, user, save } = await setup()
    await user.selectOptions(screen.getByLabelText('Тип'), 'payment')
    const field = screen.getByLabelText(/^Сумма, ₽/)

    await user.type(field, 'много')
    await save()
    expect(onSubmit).not.toHaveBeenCalled()

    await user.clear(field)
    await user.type(field, '25 000,00')
    await save()
    expect(onSubmit.mock.calls[0][0].amount_kopecks).toBe(2_500_000)

    // у отчёта суммы нет
    await user.selectOptions(screen.getByLabelText('Тип'), 'report')
    expect(screen.queryByLabelText(/^Сумма, ₽/)).toBeNull()
    await save()
    expect(onSubmit.mock.calls[1][0].amount_kopecks).toBeNull()
  })
})
