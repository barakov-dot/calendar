import { Checkbox, Field, Select } from '../../components/ui'
import {
  type CompanyForm,
  ENTITY_NAMES,
  type EntityType,
  isAusn,
  PROFIT_NAMES,
  type ProfitAdvances,
  type Regime,
  REGIME_NAMES,
  withRegime,
} from '../../lib/company'

interface Props {
  form: CompanyForm
  onChange: (form: CompanyForm) => void
}

const day = (text: string) => (text === '' ? null : Number(text))

const options = (names: Record<string, string>) =>
  Object.entries(names).map(([value, title]) => (
    <option key={value} value={value}>
      {title}
    </option>
  ))

export function RequisiteFields({ form, onChange }: Props) {
  const bind = (name: 'inn' | 'kpp' | 'ogrn' | 'name' | 'short_name' | 'address' | 'okved') => ({
    value: form[name],
    onChange: (event: { target: { value: string } }) =>
      onChange({ ...form, [name]: event.target.value }),
  })
  const isOoo = form.entity_type === 'ooo'
  return (
    <>
      <Select
        label="Тип лица"
        value={form.entity_type}
        onChange={(event) =>
          onChange({ ...form, entity_type: event.target.value as EntityType })
        }
      >
        {options(ENTITY_NAMES)}
      </Select>
      <Field
        label="ИНН"
        inputMode="numeric"
        maxLength={12}
        hint={isOoo ? '10 цифр' : '12 цифр'}
        {...bind('inn')}
      />
      <Field label="Название" {...bind('name')} />
      <Field label="Краткое название" {...bind('short_name')} />
      {!isOoo && (
        <Field
          label="Дата регистрации ИП"
          type="date"
          value={form.registration_date ?? ''}
          hint="Если ИП зарегистрирован в этом году, взносы за себя считаются с этой даты"
          onChange={(event) =>
            onChange({ ...form, registration_date: event.target.value || null })
          }
        />
      )}
      <div className="grid gap-4 sm:grid-cols-2">
        {isOoo && <Field label="КПП" maxLength={9} {...bind('kpp')} />}
        <Field label={isOoo ? 'ОГРН' : 'ОГРНИП'} maxLength={15} {...bind('ogrn')} />
        <Field label="ОКВЭД" {...bind('okved')} />
      </div>
      {isOoo && (
        <Field
          label="Руководитель"
          value={form.director_name}
          onChange={(event) => onChange({ ...form, director_name: event.target.value })}
        />
      )}
      <Field label="Адрес" {...bind('address')} />
    </>
  )
}

export function TaxFields({ form, onChange }: Props) {
  const change = (patch: Partial<CompanyForm>) => onChange({ ...form, ...patch })
  const isOoo = form.entity_type === 'ooo'
  return (
    <>
      <Field
        label="Начало ведения в календаре"
        type="date"
        value={form.calendar_start ?? ''}
        hint="Сроки раньше этой даты не считаются пропущенными и не напоминают о себе. Суммы и отметки в них можно менять."
        onChange={(event) => onChange({ ...form, calendar_start: event.target.value || null })}
      />
      <Select
        label="Режим налогообложения"
        value={form.main_regime}
        onChange={(event) => onChange(withRegime(form, event.target.value as Regime))}
      >
        {options(REGIME_NAMES)}
      </Select>
      <Checkbox
        label="Плательщик НДС"
        checked={!isAusn(form.main_regime) && form.nds_payer}
        disabled={isAusn(form.main_regime)}
        onChange={(nds_payer) => change({ nds_payer })}
      />
      <Checkbox
        label="Есть сотрудники"
        checked={form.has_employees}
        onChange={(has_employees) => change({ has_employees })}
      />
      {isOoo && form.main_regime === 'osno' && (
        <Select
          label="Авансы по налогу на прибыль"
          value={form.profit_advances_mode ?? 'monthly_by_quarter'}
          onChange={(event) =>
            change({ profit_advances_mode: event.target.value as ProfitAdvances })
          }
        >
          {options(PROFIT_NAMES)}
        </Select>
      )}
      {isOoo && (
        <>
          <Checkbox
            label="Имущество по среднегодовой стоимости"
            checked={form.has_property_avg}
            onChange={(has_property_avg) => change({ has_property_avg })}
          />
          <Checkbox
            label="Имущество по кадастровой стоимости"
            checked={form.has_property_cadastral}
            onChange={(has_property_cadastral) => change({ has_property_cadastral })}
          />
        </>
      )}
      <Checkbox
        label="Транспортный налог"
        checked={form.has_transport_tax}
        onChange={(has_transport_tax) => change({ has_transport_tax })}
      />
      <Checkbox
        label="Земельный налог"
        checked={form.has_land_tax}
        onChange={(has_land_tax) => change({ has_land_tax })}
      />
      {isOoo && (
        <Checkbox
          label="Платит авансы по имущественным налогам"
          checked={form.has_property_advances}
          onChange={(has_property_advances) => change({ has_property_advances })}
        />
      )}
      {form.has_employees && (
        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            label="Аванс: число месяца"
            type="number"
            min={1}
            max={31}
            value={form.advance_day ?? ''}
            onChange={(event) => change({ advance_day: day(event.target.value) })}
          />
          <Field
            label="Зарплата: число месяца"
            type="number"
            min={1}
            max={31}
            value={form.salary_day ?? ''}
            hint="1–15 — за прошлый месяц, 16–31 — за текущий"
            onChange={(event) => change({ salary_day: day(event.target.value) })}
          />
        </div>
      )}
      {form.has_employees && (
        <Checkbox
          label="Есть дополнительные взносы на накопительную пенсию (ДСВ)"
          checked={form.has_dsv}
          onChange={(has_dsv) => change({ has_dsv })}
        />
      )}
      {form.has_employees && isAusn(form.main_regime) && (
        <Checkbox
          label="Создавать задачи по НДФЛ (АУСН)"
          checked={form.ausn_ndfl_tasks}
          onChange={(ausn_ndfl_tasks) => change({ ausn_ndfl_tasks })}
        />
      )}
      <Checkbox
        label="Торговый сбор"
        checked={form.has_trade_fee}
        onChange={(has_trade_fee) => change({ has_trade_fee })}
      />
      <Checkbox
        label="Туристический налог"
        checked={form.has_tourist_tax}
        onChange={(has_tourist_tax) => change({ has_tourist_tax })}
      />
      <label className="block text-sm">
        <span className="mb-1 block font-medium">Заметки (клиент их не видит)</span>
        <textarea
          className="w-full rounded-lg border border-slate-300 bg-transparent px-3 py-2 dark:border-slate-600"
          rows={3}
          value={form.notes}
          onChange={(event) => change({ notes: event.target.value })}
        />
      </label>
    </>
  )
}
