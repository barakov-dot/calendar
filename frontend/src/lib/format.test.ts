import { describe, expect, it } from 'vitest'

import { formatDateTime, parseOffsets } from './format'

describe('parseOffsets', () => {
  it('разбирает список дней', () => {
    expect(parseOffsets('1, 7;3 3')).toEqual([7, 3, 1])
    expect(parseOffsets('')).toEqual([])
  })

  it.each(['0', '400', '1.5', 'три', '-1'])('отклоняет %s', (text) => {
    expect(parseOffsets(text)).toBeNull()
  })
})

it('показывает время по Москве', () => {
  expect(formatDateTime('2026-11-26T22:30:00Z')).toContain('27 нояб')
})
