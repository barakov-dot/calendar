import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import InviteList from './InviteList'

const telegram = vi.hoisted(() => ({ initData: null as string | null, opened: [] as string[] }))

vi.mock('../lib/telegram', () => ({
  miniAppInitData: () => telegram.initData,
  openTelegramPath: (path: string) => telegram.opened.push(path),
}))

const link = 'https://t.me/some_bot?start=inv_Abc-1'

function send() {
  render(
    <InviteList
      invites={[
        { id: 1, kind: 'accountant', link, created_at: '', expires_at: '2026-12-04T10:00:00Z' },
      ]}
      onRevoke={() => {}}
    />,
  )
  const button = screen.getByRole('link', { name: 'Отправить в Telegram' })
  // jsdom не умеет переходить по tg://, важно лишь, отменён ли переход
  const followed = fireEvent.click(button)
  return { href: button.getAttribute('href')!, followed }
}

describe('отправка приглашения', () => {
  afterEach(() => {
    cleanup()
    telegram.initData = null
    telegram.opened = []
  })

  it('из браузера открывает выбор чата в приложении, минуя сайт t.me', () => {
    const { href, followed } = send()

    expect(href.startsWith('tg://msg_url?url=')).toBe(true)
    const params = new URLSearchParams(href.split('?')[1])
    expect(params.get('url')).toBe(link)
    expect(params.get('text')).toContain('Запустить')
    expect(followed).toBe(true)
    expect(telegram.opened).toEqual([])
  })

  it('в Mini App просит открыть выбор чата сам Telegram', () => {
    telegram.initData = 'data'

    const { followed } = send()

    expect(followed).toBe(false)
    expect(telegram.opened).toHaveLength(1)
    expect(telegram.opened[0].startsWith('/share/url?url=https%3A%2F%2Ft.me%2F')).toBe(true)
  })
})
