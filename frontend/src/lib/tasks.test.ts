import { describe, expect, it } from 'vitest'

import { addDays, addMonths, monthEnd, monthGrid, statusesFor, todayIso, toneOf } from './tasks'

describe('статусы', () => {
  it('платёж отмечается оплаченным, остальное — сданным', () => {
    expect(statusesFor('payment')).toEqual(['planned', 'paid', 'not_required'])
    expect(statusesFor('report')).toEqual(['planned', 'done', 'not_required'])
  })

  it.each([
    ['planned', '2026-05-01', 'overdue'],
    ['planned', '2026-05-02', 'planned'],
    ['paid', '2026-01-01', 'closed'],
    ['done', '2027-01-01', 'closed'],
    ['not_required', '2026-01-01', 'skipped'],
  ] as const)('%s %s → %s', (status, due_date, tone) => {
    expect(toneOf({ status, due_date }, '2026-05-02')).toBe(tone)
  })
})

describe('даты', () => {
  it('сегодня считается по Москве', () => {
    expect(todayIso(new Date('2026-11-26T22:30:00Z'))).toBe('2026-11-27')
  })

  it('переходы через месяц и год', () => {
    expect(addDays('2026-12-31', 1)).toBe('2027-01-01')
    expect(addMonths('2026-12', 1)).toBe('2027-01')
    expect(addMonths('2026-01', -1)).toBe('2025-12')
    expect(monthEnd('2028-02')).toBe('2028-02-29')
  })

  it('сетка месяца начинается с понедельника', () => {
    const grid = monthGrid('2026-11') // 1 ноября — воскресенье

    expect(grid[0]).toEqual([null, null, null, null, null, null, '2026-11-01'])
    expect(grid.at(-1)?.[0]).toBe('2026-11-30')
    expect(grid.flat().filter(Boolean)).toHaveLength(30)
    expect(grid.every((week) => week.length === 7)).toBe(true)
  })
})
