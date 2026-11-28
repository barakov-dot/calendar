import { useState } from 'react'

import TextArea from '../../components/TextArea'
import { Alert, Button, Checkbox, Field, Select } from '../../components/ui'
import {
  AUDIENCE_NAMES,
  FREQUENCY_NAMES,
  type Frequency,
  type ReminderData,
  SHIFT_NAMES,
} from '../../lib/reminders'
import { parseRubles, toRublesText } from '../../lib/company'
import { addDays, KIND_NAMES, todayIso, type TaskKind } from '../../lib/tasks'

const options = (names: Record<string, string>) =>
  Object.entries(names).map(([value, title]) => (
    <option key={value} value={value}>
      {title}
    </option>
  ))

export default function ReminderForm({
  companyId,
  initial,
  onSubmit,
  onCancel,
}: {
  companyId: number | null
  initial?: ReminderData
  onSubmit: (data: ReminderData) => void
  onCancel: () => void
}) {
  const [form, setForm] = useState<ReminderData>(
    initial ?? {
      company_id: companyId,
      title: '',
      description: '',
      kind: 'other',
      amount_kopecks: null,
      schedule: { frequency: 'monthly', day_of_month: 10, interval_weeks: null },
      dtstart: todayIso(),
      until: null,
      shift_rule: 'next_workday',
      audience: 'accountant',
      is_active: true,
    },
  )
  const change = (patch: Partial<ReminderData>) => setForm({ ...form, ...patch })
  const [amount, setAmount] = useState(() => toRublesText(form.amount_kopecks))
  const hasAmount = form.kind === 'payment' || form.kind === 'other'
  const kopecks = hasAmount ? parseRubles(amount) : null
  const weekly = form.schedule.frequency === 'weekly'
  const number = weekly ? form.schedule.interval_weeks : form.schedule.day_of_month
  const endless = form.until === null
  const endsEarly = !!form.until && form.until < form.dtstart
  const valid =
    kopecks !== undefined &&
    form.title.trim() !== '' &&
    form.dtstart !== '' &&
    (endless || (form.until !== '' && !endsEarly)) &&
    Number.isInteger(number) &&
    Number(number) >= 1 &&
    Number(number) <= (weekly ? 52 : 31)

  return (
    <div className="space-y-3 rounded-lg border border-slate-200 p-3 dark:border-slate-700">
      <Field label="Название" value={form.title} onChange={(e) => change({ title: e.target.value })} />
      <TextArea label="Описание" value={form.description} onChange={(description) => change({ description })} />
      <Select label="Тип" value={form.kind} onChange={(e) => change({ kind: e.target.value as TaskKind })}>
        {options(KIND_NAMES)}
      </Select>
      {hasAmount && (
        <Field
          label="Сумма, ₽ (необязательно)"
          inputMode="decimal"
          value={amount}
          hint="Подставится в каждую задачу. В отдельной задаче сумму можно изменить."
          onChange={(event) => setAmount(event.target.value)}
        />
      )}
      {kopecks === undefined && (
        <Alert kind="error">Сумма — число, например 25000 или 25000,50.</Alert>
      )}
      <Select
        label="Повторять"
        value={form.schedule.frequency}
        onChange={(event) => {
          const frequency = event.target.value as Frequency
          change({
            schedule:
              frequency === 'weekly'
                ? { frequency, day_of_month: null, interval_weeks: 1 }
                : { frequency, day_of_month: form.schedule.day_of_month ?? 10, interval_weeks: null },
          })
        }}
      >
        {options(FREQUENCY_NAMES)}
      </Select>
      <Field
        label={weekly ? 'Раз во сколько недель' : 'Число месяца'}
        type="number"
        min={1}
        max={weekly ? 52 : 31}
        value={number ?? ''}
        hint={
          weekly
            ? 'День недели — как у даты начала'
            : 'Если такого числа в месяце нет — последний день. Месяцы отсчитываются от даты начала.'
        }
        onChange={(event) => {
          const value = event.target.value === '' ? null : Number(event.target.value)
          change({
            schedule: { ...form.schedule, [weekly ? 'interval_weeks' : 'day_of_month']: value },
          })
        }}
      />
      <Field
        label="Начиная с"
        type="date"
        value={form.dtstart}
        onChange={(e) => change({ dtstart: e.target.value })}
      />
      {/* пустое поле даты Safari рисует сегодняшним числом, поэтому «без срока» — галочкой */}
      <Checkbox
        label="Бессрочно (без даты окончания)"
        checked={endless}
        onChange={(checked) =>
          change({ until: checked ? null : addDays(form.dtstart || todayIso(), 365) })
        }
      />
      {!endless && (
        <Field
          label="Действует до"
          type="date"
          value={form.until ?? ''}
          onChange={(e) => change({ until: e.target.value })}
        />
      )}
      {endsEarly && <Alert kind="error">Дата окончания раньше даты начала.</Alert>}
      <Select
        label="Если выпадает на выходной"
        value={form.shift_rule}
        onChange={(e) => change({ shift_rule: e.target.value as ReminderData['shift_rule'] })}
      >
        {options(SHIFT_NAMES)}
      </Select>
      {form.company_id !== null && (
        <Select
          label="Кому"
          value={form.audience}
          onChange={(e) => change({ audience: e.target.value as ReminderData['audience'] })}
        >
          {options(AUDIENCE_NAMES)}
        </Select>
      )}
      <Checkbox label="Включено" checked={form.is_active} onChange={(is_active) => change({ is_active })} />
      <div className="flex gap-2">
        <Button disabled={!valid} onClick={() => onSubmit({ ...form, amount_kopecks: kopecks ?? null })}>
          Сохранить напоминание
        </Button>
        <Button variant="secondary" onClick={onCancel}>
          Отмена
        </Button>
      </div>
    </div>
  )
}
