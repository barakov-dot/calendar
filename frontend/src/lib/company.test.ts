import { describe, expect, it } from 'vitest'

import {
  EMPTY_COMPANY,
  formatDate,
  formatKopecks,
  parseRubles,
  toForm,
  withRegime,
} from './company'

describe('деньги в копейках', () => {
  it.each([
    ['36 000,50', 3600050],
    ['0.07', 7],
    ['1.1', 110],
    ['100', 10000],
    ['', null],
  ])('%s → %s', (text, kopecks) => {
    expect(parseRubles(text)).toBe(kopecks)
  })

  it.each(['1,234', '-1', 'abc', '1e3', '99999999999999999'])('отклоняет %s', (text) => {
    expect(parseRubles(text)).toBeUndefined()
  })

  it('форматирует', () => {
    expect(formatKopecks(3600005).replace(/\s/g, ' ')).toBe('36 000,05 ₽')
  })
})

it('форма берёт только редактируемые поля', () => {
  const form = toForm({ name: 'X', profit_advances_mode: null, ...{ id: 5, status: 'A' } })

  expect(Object.keys(form)).toEqual(Object.keys(EMPTY_COMPANY))
  expect(form.name).toBe('X')
})

it('НДС по умолчанию только на ОСНО', () => {
  expect(withRegime(EMPTY_COMPANY, 'osno').nds_payer).toBe(true)
  expect(withRegime(EMPTY_COMPANY, 'usn15').nds_payer).toBe(false)
})

it('дата без часовых поясов', () => {
  expect(formatDate('2026-01-31')).toBe('31.01.2026')
})
