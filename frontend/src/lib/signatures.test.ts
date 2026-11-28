import { describe, expect, it } from 'vitest'

import { joinHolder, OTHER, splitHolder } from './signatures'

const roles = ['Генеральный директор', 'Менеджер']

describe('владелец подписи', () => {
  it.each([
    ['', { role: 'Генеральный директор', name: '' }],
    ['Менеджер', { role: 'Менеджер', name: '' }],
    ['Менеджер — Иванова И.И.', { role: 'Менеджер', name: 'Иванова И.И.' }],
    // вписанное раньше вручную остаётся как есть
    ['Директор Петров', { role: OTHER, name: 'Директор Петров' }],
    ['Менеджер по продажам', { role: OTHER, name: 'Менеджер по продажам' }],
  ])('разбирает «%s»', (holder, expected) => {
    expect(splitHolder(holder, roles)).toEqual(expected)
    if (holder) expect(joinHolder(splitHolder(holder, roles))).toBe(holder)
  })

  it('без ФИО сохраняет только название из списка', () => {
    expect(joinHolder({ role: 'Менеджер', name: '  ' })).toBe('Менеджер')
    expect(joinHolder({ role: OTHER, name: ' ' })).toBe('')
  })
})
