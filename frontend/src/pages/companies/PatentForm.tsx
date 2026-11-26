import { useState } from 'react'

import { Alert, Button, Field } from '../../components/ui'
import { parseRubles } from '../../lib/company'
import type { Patent } from '../../lib/types'

export type PatentData = Omit<Patent, 'id'>

const toText = (kopecks: number | null | undefined) =>
  kopecks == null ? '' : (kopecks / 100).toFixed(2).replace('.', ',')

export default function PatentForm({
  initial,
  submitLabel,
  onSubmit,
  onCancel,
}: {
  initial?: PatentData
  submitLabel: string
  onSubmit: (patent: PatentData) => void
  onCancel: () => void
}) {
  const [number, setNumber] = useState(initial?.number ?? '')
  const [region, setRegion] = useState(initial?.region ?? '')
  const [start, setStart] = useState(initial?.date_start ?? '')
  const [end, setEnd] = useState(initial?.date_end ?? '')
  const [cost, setCost] = useState(toText(initial?.cost_kopecks))
  const kopecks = parseRubles(cost)

  return (
    <div className="space-y-3 rounded-lg border border-slate-200 p-3 dark:border-slate-700">
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Номер патента" value={number} onChange={(e) => setNumber(e.target.value)} />
        <Field label="Регион" value={region} onChange={(e) => setRegion(e.target.value)} />
        <Field label="Начало" type="date" value={start} onChange={(e) => setStart(e.target.value)} />
        <Field label="Окончание" type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
        <Field
          label="Стоимость, ₽"
          inputMode="decimal"
          value={cost}
          onChange={(e) => setCost(e.target.value)}
        />
      </div>
      {kopecks === undefined && <Alert kind="error">Стоимость — число, например 36 000,50.</Alert>}
      <div className="flex gap-2">
        <Button
          disabled={!start || !end || kopecks === undefined}
          onClick={() =>
            kopecks !== undefined &&
            onSubmit({ number, region, date_start: start, date_end: end, cost_kopecks: kopecks })
          }
        >
          {submitLabel}
        </Button>
        <Button variant="secondary" onClick={onCancel}>
          Отмена
        </Button>
      </div>
    </div>
  )
}
