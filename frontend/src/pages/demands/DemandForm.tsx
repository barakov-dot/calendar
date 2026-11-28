import { keepPreviousData, useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import TextArea from '../../components/TextArea'
import { Alert, Button, Card, Checkbox, ErrorText, Field, Select } from '../../components/ui'
import { api } from '../../lib/api'
import { formatDate, parseRubles } from '../../lib/company'
import type { DemandKind, DemandValues } from '../../lib/demands'
import { todayIso } from '../../lib/tasks'
import { useCompanies } from '../../lib/useCompanies'

export interface DemandBody {
  company_id: number
  knd: string
  number: string
  doc_date: string
  sent_date: string | null
  receipt_date: string | null
  response_workdays: number | null
  response_date: string | null
  amount_kopecks: number | null
  note: string
  receipt_done?: boolean
}

interface Dates {
  receipt_date: string
  response_date: string | null
}

/** Дата введена целиком: пока набирают год, сервер не спрашиваем. */
const entered = (text: string) => (/^20[2-9]\d-/.test(text) ? text : null)

/** Подпись под датой, которую считает сервис, но можно заменить своей. */
function DateOrigin({ manual, auto, reset }: { manual: boolean; auto: string; reset: () => void }) {
  return manual ? (
    <>
      Задано вручную.{' '}
      <button type="button" onClick={reset} className="cursor-pointer text-blue-600 underline">
        Посчитать заново
      </button>
    </>
  ) : (
    auto
  )
}

/** Реквизиты и сроки требования. Даты квитанции и исполнения считаются сами и
 *  подставляются в поля; введённые вручную остаются как есть. */
export default function DemandForm({
  initial,
  isNew,
  submitLabel,
  onSubmit,
  onCancel,
}: {
  initial: DemandValues
  isNew: boolean
  submitLabel: string
  onSubmit: (body: DemandBody) => Promise<unknown>
  onCancel: () => void
}) {
  const [form, setForm] = useState(initial)
  const [signed, setSigned] = useState<boolean | null>(null)
  const change = (patch: Partial<DemandValues>) => setForm({ ...form, ...patch })
  const companies = useCompanies()
  const kinds = useQuery({
    queryKey: ['demand-types'],
    queryFn: () => api<DemandKind[]>('/demands/types'),
  })
  // последним в списке идёт «другой документ» с пустым кодом
  const kind =
    kinds.data?.find((item) => item.knd === form.knd) ?? kinds.data?.[kinds.data.length - 1]
  const terms = {
    knd: form.knd,
    doc_date: form.doc_date,
    sent_date: form.sent_date || null,
    receipt_date: entered(form.receipt_date),
    response_workdays: form.response_workdays ? Number(form.response_workdays) : null,
    response_date: entered(form.response_date),
  }
  const dates = useQuery({
    queryKey: ['demand-dates', terms],
    queryFn: () => api<Dates>('/demands/dates', { method: 'POST', body: terms }),
    enabled: entered(form.doc_date) !== null,
    // пока считается новый срок, в полях остаётся прежний
    placeholderData: keepPreviousData,
  })
  const kopecks = parseRubles(form.amount)
  const receipt = dates.data?.receipt_date
  const receiptDone = signed ?? (!!receipt && receipt < todayIso())
  const response = dates.data?.response_date
  const label = kind?.response_label ?? 'Срок исполнения'
  const save = useMutation({
    mutationFn: () =>
      onSubmit({
        ...terms,
        company_id: form.company_id,
        number: form.number.trim(),
        amount_kopecks: kopecks ?? null,
        note: form.note,
        ...(isNew ? { receipt_done: receiptDone } : {}),
      }),
  })
  const ready = form.company_id > 0 && !!response && kopecks !== undefined

  return (
    <Card title={isNew ? 'Новое требование' : 'Изменить требование'}>
      <Select
        label="Организация"
        value={form.company_id}
        disabled={!isNew}
        onChange={(event) => change({ company_id: Number(event.target.value) })}
      >
        <option value={0}>Выберите организацию</option>
        {companies.data?.map((company) => (
          <option key={company.id} value={company.id}>
            {company.short_name || company.name}
          </option>
        ))}
      </Select>
      <Select label="Вид" value={form.knd} onChange={(event) => change({ knd: event.target.value })}>
        {/* неизвестный код из файла тоже остаётся выбранным */}
        {form.knd && !kinds.data?.some((item) => item.knd === form.knd) && (
          <option value={form.knd}>КНД {form.knd} — другой документ</option>
        )}
        {kinds.data?.map((item) => (
          <option key={item.knd} value={item.knd}>
            {item.knd ? `${item.name} (КНД ${item.knd})` : item.name}
          </option>
        ))}
      </Select>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field
          label="Номер"
          value={form.number}
          onChange={(event) => change({ number: event.target.value })}
        />
        <Field
          label="Дата документа"
          type="date"
          value={form.doc_date}
          onChange={(event) => change({ doc_date: event.target.value })}
        />
        <Field
          label="Дата получения требования"
          type="date"
          value={form.sent_date || form.doc_date}
          hint={
            <DateOrigin
              manual={form.sent_date !== ''}
              auto="Как дата документа"
              reset={() => change({ sent_date: '' })}
            />
          }
          onChange={(event) => change({ sent_date: event.target.value })}
        />
        <Field
          label="Дата квитанции о приёме"
          type="date"
          value={form.receipt_date || (receipt ?? '')}
          hint={
            <DateOrigin
              manual={form.receipt_date !== ''}
              auto="6-й рабочий день после получения"
              reset={() => change({ receipt_date: '' })}
            />
          }
          onChange={(event) => change({ receipt_date: event.target.value })}
        />
        <Field
          label="Срок ответа, рабочих дней"
          type="number"
          min={1}
          max={60}
          value={form.response_workdays}
          placeholder={kind?.response_workdays ? String(kind.response_workdays) : ''}
          hint={
            kind?.response_workdays
              ? `Со дня квитанции. Пусто — ${kind.response_workdays}`
              : 'Со дня квитанции'
          }
          // новый срок в днях заменяет дату, введённую раньше
          onChange={(event) =>
            change({ response_workdays: event.target.value, response_date: '' })
          }
        />
        <Field
          label={label}
          type="date"
          value={form.response_date || (response ?? '')}
          hint={
            <DateOrigin
              manual={form.response_date !== ''}
              auto={
                kind?.due_on_upload
                  ? 'День загрузки: решение исполняется сразу'
                  : response
                    ? 'Считается от даты квитанции'
                    : 'Укажите дату из документа или срок в рабочих днях'
              }
              reset={() => change({ response_date: '' })}
            />
          }
          onChange={(event) => change({ response_date: event.target.value })}
        />
        <Field
          label="Сумма, ₽"
          inputMode="decimal"
          value={form.amount}
          hint={kind?.is_payment ? undefined : 'Если есть в документе'}
          onChange={(event) => change({ amount: event.target.value })}
        />
      </div>
      {kopecks === undefined && <Alert kind="error">Сумма — число, например 36 000,50.</Alert>}
      <TextArea label="Комментарий" value={form.note} onChange={(note) => change({ note })} />
      {receipt && (
        <Alert kind={response ? 'success' : 'warning'}>
          Квитанция — {formatDate(receipt)}.{' '}
          {response ? `${label} — ${formatDate(response)}.` : `Укажите: ${label.toLowerCase()}.`}
        </Alert>
      )}
      {isNew && (
        <Checkbox label="Квитанция уже подписана" checked={receiptDone} onChange={setSigned} />
      )}
      <ErrorText error={dates.error ?? save.error} />
      <div className="flex flex-wrap gap-2">
        <Button disabled={!ready || save.isPending} onClick={() => save.mutate()}>
          {submitLabel}
        </Button>
        <Button variant="secondary" onClick={onCancel}>
          Отмена
        </Button>
      </div>
    </Card>
  )
}
