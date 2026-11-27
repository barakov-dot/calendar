import { describe, expect, it } from 'vitest'

import { previousMonth } from '../../lib/tasks'

describe('период отчёта по умолчанию', () => {
  it.each([
    ['2026-11-27', '2026-10-01', '2026-10-31'],
    ['2027-01-05', '2026-12-01', '2026-12-31'],
    ['2028-03-31', '2028-02-01', '2028-02-29'],
  ])('%s → прошлый месяц', (today, from, to) => {
    expect(previousMonth(today)).toEqual({ from, to })
  })
})
