import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'

import { Field } from './ui'

afterEach(cleanup)

it('нажатие на поле даты открывает календарь, на обычное поле — нет', async () => {
  const showPicker = vi.fn()
  HTMLInputElement.prototype.showPicker = showPicker
  render(
    <>
      <Field label="С" type="date" />
      <Field label="Название" />
    </>,
  )
  const user = userEvent.setup()

  await user.click(screen.getByLabelText('Название'))
  expect(showPicker).not.toHaveBeenCalled()
  await user.click(screen.getByLabelText('С'))
  expect(showPicker).toHaveBeenCalledOnce()
})
