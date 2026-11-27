export type EntityType = 'ooo' | 'ip'
export type Regime = 'osno' | 'usn6' | 'usn15' | 'ausn_income' | 'ausn_income_expense'
export type ProfitAdvances = 'quarterly' | 'monthly_by_quarter' | 'monthly_actual'

export const ENTITY_NAMES: Record<EntityType, string> = { ooo: 'ООО', ip: 'ИП' }

export const REGIME_NAMES: Record<Regime, string> = {
  osno: 'ОСНО',
  usn6: 'УСН «Доходы» 6%',
  usn15: 'УСН «Доходы минус расходы» 15%',
  ausn_income: 'АУСН «Доходы»',
  ausn_income_expense: 'АУСН «Доходы минус расходы»',
}

export const PROFIT_NAMES: Record<ProfitAdvances, string> = {
  quarterly: 'Поквартально',
  monthly_by_quarter: 'Ежемесячно по прибыли прошлого квартала',
  monthly_actual: 'Ежемесячно по фактической прибыли',
}

/** Редактируемые поля компании — то, что отправляется на сервер. */
export interface CompanyForm {
  inn: string
  kpp: string
  ogrn: string
  /** Дата регистрации ИП: с неё считаются взносы за себя. */
  registration_date: string | null
  /** С какой даты ведётся календарь: более ранние сроки не считаются пропущенными. */
  calendar_start: string | null
  name: string
  short_name: string
  address: string
  okved: string
  director_name: string
  region_code: string
  entity_type: EntityType
  main_regime: Regime
  nds_payer: boolean
  has_employees: boolean
  /** Сотрудники есть, но выплат им нет: без зарплаты и НДФЛ. */
  no_salary: boolean
  profit_advances_mode: ProfitAdvances | null
  has_property_avg: boolean
  has_property_cadastral: boolean
  has_property_advances: boolean
  has_transport_tax: boolean
  has_land_tax: boolean
  has_trade_fee: boolean
  has_tourist_tax: boolean
  has_dsv: boolean
  ausn_ndfl_tasks: boolean
  advance_day: number | null
  salary_day: number | null
  notes: string
}

export const EMPTY_COMPANY: CompanyForm = {
  inn: '',
  kpp: '',
  ogrn: '',
  registration_date: null,
  calendar_start: null,
  name: '',
  short_name: '',
  address: '',
  okved: '',
  director_name: '',
  region_code: '',
  entity_type: 'ooo',
  main_regime: 'usn6',
  nds_payer: false,
  has_employees: false,
  no_salary: false,
  profit_advances_mode: null,
  has_property_avg: false,
  has_property_cadastral: false,
  has_property_advances: false,
  has_transport_tax: false,
  has_land_tax: false,
  has_trade_fee: false,
  has_tourist_tax: false,
  has_dsv: false,
  ausn_ndfl_tasks: true,
  advance_day: null,
  salary_day: null,
  notes: '',
}

/** Только редактируемые поля из объекта с любым набором свойств. */
export function toForm(source: Partial<CompanyForm>): CompanyForm {
  const entries = Object.entries(EMPTY_COMPANY).map(([key, fallback]) => {
    const value = source[key as keyof CompanyForm]
    return [key, value === undefined ? fallback : value]
  })
  return Object.fromEntries(entries) as unknown as CompanyForm
}

export const isAusn = (regime: Regime) => regime.startsWith('ausn')

/** При смене режима НДС получает значение по умолчанию: платят на ОСНО. */
export function withRegime(form: CompanyForm, regime: Regime): CompanyForm {
  return { ...form, main_regime: regime, nds_payer: regime === 'osno' }
}

const MAX_KOPECKS = Number.MAX_SAFE_INTEGER

/** «12 345,6» → 1234560 копеек без вычислений с дробями.
 *  Пустая строка → null, неверная → undefined. */
export function parseRubles(text: string): number | null | undefined {
  const compact = text.replace(/\s/g, '')
  if (!compact) return null
  const match = /^(\d+)(?:[.,](\d{1,2}))?$/.exec(compact)
  if (!match) return undefined
  const kopecks = Number(match[1]) * 100 + Number((match[2] ?? '').padEnd(2, '0'))
  return kopecks <= MAX_KOPECKS ? kopecks : undefined
}

/** 1234560 → «12345,60» для поля ввода. */
export const toRublesText = (kopecks: number | null | undefined) =>
  kopecks == null
    ? ''
    : `${Math.floor(kopecks / 100)},${String(kopecks % 100).padStart(2, '0')}`

export function formatKopecks(kopecks: number): string {
  const rubles = Math.floor(kopecks / 100).toLocaleString('ru-RU')
  return `${rubles},${String(kopecks % 100).padStart(2, '0')} ₽`
}

/** «2026-12-31» → «31.12.2026» без часовых поясов. */
export const formatDate = (iso: string) => iso.split('-').reverse().join('.')
