import { expect, it } from 'vitest'

import { chatTarget, userTarget } from './telegramLinks'

it('ссылка на бота открывает приложение с параметром запуска', () => {
  expect(chatTarget('https://t.me/some_bot?start=login_a-B_1')).toEqual({
    href: 'tg://resolve?domain=some_bot&start=login_a-B_1',
    path: '/some_bot?start=login_a-B_1',
  })
})

it('ссылка на человека открывает чат', () => {
  expect(userTarget('anna')).toEqual({ href: 'tg://resolve?domain=anna', path: '/anna' })
})
