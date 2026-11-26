import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { isDarkColor } from '../lib/telegram'
import ThemeToggle from './ThemeToggle'

describe('тема', () => {
  it('переключается и запоминается', async () => {
    const user = userEvent.setup()
    const dark = () => document.documentElement.classList.contains('dark')
    render(<ThemeToggle />)
    expect(dark()).toBe(false)

    await user.click(screen.getByRole('button', { name: 'Ночная тема' }))
    expect(dark()).toBe(true)
    expect(localStorage.getItem('buh.theme')).toBe('dark')

    await user.click(screen.getByRole('button', { name: 'Тема как в системе' }))
    expect(dark()).toBe(false)
    expect(localStorage.getItem('buh.theme')).toBeNull()
  })

  it('распознаёт тёмный фон Telegram', () => {
    expect(isDarkColor('#17212b')).toBe(true)
    expect(isDarkColor('#ffffff')).toBe(false)
    expect(isDarkColor(undefined)).toBeNull()
  })
})
