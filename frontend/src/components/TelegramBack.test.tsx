import { act, cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BrowserRouter, Link, Route, Routes } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { coverBack } from '../lib/backStack'
import TelegramBack from './TelegramBack'

const telegram = vi.hoisted(() => ({
  initData: 'data' as string | null,
  press: null as (() => void) | null,
}))

vi.mock('../lib/telegram', () => ({
  miniAppInitData: () => telegram.initData,
  showBackButton: (onPress: () => void) => {
    telegram.press = onPress
    return () => {
      telegram.press = null
    }
  },
}))

function open(path: string) {
  window.history.replaceState(null, '', path)
  render(
    <BrowserRouter>
      <TelegramBack client={false} />
      <Routes>
        <Route path="/" element={<Link to="/calendar">главная</Link>} />
        <Route path="/calendar" element={<p>календарь</p>} />
        <Route path="/users" element={<p>список</p>} />
        <Route path="/users/:id" element={<p>карточка</p>} />
        <Route path="/reports" element={<p>отчёты</p>} />
        <Route path="/more" element={<p>разделы</p>} />
      </Routes>
    </BrowserRouter>,
  )
  return userEvent.setup()
}

// переход назад по истории браузер выполняет не сразу
const press = () => act(async () => telegram.press!())

describe('кнопка «Назад» в Mini App', () => {
  beforeEach(() => {
    telegram.initData = 'data'
    telegram.press = null
  })
  afterEach(cleanup)

  it('на главной её нет, дальше возвращает на прошлую страницу', async () => {
    const user = open('/')
    expect(telegram.press).toBeNull()

    await user.click(screen.getByText('главная'))
    screen.getByText('календарь')
    await press()

    await screen.findByText('главная')
    expect(telegram.press).toBeNull()
  })

  it.each([
    ['/users/7', 'список'],
    ['/reports', 'разделы'],
    ['/calendar', 'главная'],
  ])('со страницы %s, открытой первой, ведёт уровнем выше', async (path, parent) => {
    open(path)

    await press()

    screen.getByText(parent)
  })

  it('сначала закрывает окно поверх страницы', async () => {
    open('/reports')
    const close = vi.fn()
    const uncover = coverBack(close)

    await press()

    expect(close).toHaveBeenCalledOnce()
    screen.getByText('отчёты')
    uncover()
    await press()
    screen.getByText('разделы')
  })

  it('в обычном браузере не появляется', () => {
    telegram.initData = null
    open('/reports')
    expect(telegram.press).toBeNull()
  })
})
