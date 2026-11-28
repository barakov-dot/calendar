import { useState } from 'react'
import { Link } from 'react-router'

import { Button, Card } from '../../components/ui'
import { formatDate, formatKopecks } from '../../lib/company'
import { type ReportRow, type Result, RESULT_NAMES, RESULTS } from './report'

const PAGE = 200

const COLORS: Record<Result, string> = {
  on_time: 'text-green-700 dark:text-green-300',
  late: 'text-amber-700 dark:text-amber-300',
  not_required: 'text-slate-500 dark:text-slate-400',
  overdue: 'text-red-700 dark:text-red-300',
}

/** Задачи отчёта: все или отобранные по организации и колонке итогов. */
export default function ReportTasks({
  rows,
  companyName,
  result,
  onSelect,
}: {
  /** Уже отобранные по организации. */
  rows: ReportRow[]
  /** Пусто — все организации. */
  companyName: string
  result: Result | null
  onSelect: (result: Result | null, allCompanies?: boolean) => void
}) {
  const [limit, setLimit] = useState(PAGE)
  const found = result ? rows.filter((row) => row.result === result) : rows
  const filters: [Result | null, string, number][] = [
    [null, 'Все', rows.length],
    ...RESULTS.map((key): [Result, string, number] => [
      key,
      RESULT_NAMES[key],
      rows.filter((row) => row.result === key).length,
    ]),
  ]

  return (
    <Card title={`Задачи: ${companyName || 'все организации'}`}>
      {companyName && (
        <Button variant="secondary" onClick={() => onSelect(result, true)}>
          Показать все организации
        </Button>
      )}
      <div className="flex flex-wrap gap-2" role="group" aria-label="Какие задачи показать">
        {filters.map(([key, title, count]) => (
          <button
            key={title}
            type="button"
            aria-pressed={key === result}
            onClick={() => onSelect(key)}
            className={`rounded-full border px-3 py-1 text-sm ${
              key === result
                ? 'border-blue-600 bg-blue-600 text-white'
                : 'border-slate-300 dark:border-slate-600'
            }`}
          >
            {title} · {count}
          </button>
        ))}
      </div>
      {found.length === 0 && <p className="text-sm">Таких задач нет.</p>}
      <ul className="divide-y divide-slate-200 text-sm dark:divide-slate-700">
        {found.slice(0, limit).map((row) => (
          <li key={row.task_id} className="space-y-0.5 py-2">
            <div className="flex items-start justify-between gap-3">
              <Link
                to={`/tasks/${row.task_id}`}
                className="min-w-0 font-medium break-words text-blue-700 underline dark:text-blue-300"
              >
                {row.title}
              </Link>
              {row.amount_kopecks !== null && (
                <span className="shrink-0 tabular-nums">{formatKopecks(row.amount_kopecks)}</span>
              )}
            </div>
            <div className="text-slate-500 dark:text-slate-400">
              {!companyName && `${row.company} · `}
              {row.kind} · срок {formatDate(row.due)} · {row.accountant}
            </div>
            <div className={COLORS[row.result]}>
              {row.result === 'overdue'
                ? 'Просрочено, не отмечено'
                : `${row.status} ${row.marked ? formatDate(row.marked) : ''}`}
              {row.result === 'on_time' && ' · в срок'}
              {row.result === 'late' && ` · ${row.timing.toLowerCase()}`}
              {row.marked_by && ` · ${row.marked_by}`}
            </div>
          </li>
        ))}
      </ul>
      {found.length > limit && (
        <Button variant="secondary" onClick={() => setLimit(limit + PAGE)}>
          Показать ещё ({found.length - limit})
        </Button>
      )}
    </Card>
  )
}
