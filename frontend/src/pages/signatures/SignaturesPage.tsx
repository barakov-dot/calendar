import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router'

import { ErrorText, Field } from '../../components/ui'
import { api } from '../../lib/api'
import { formatDate } from '../../lib/company'
import { URGENCY_STYLES, urgencyOf } from '../../lib/signatures'

export interface SignatureRow {
  id: number
  company_id: number
  company_name: string
  holder: string
  expires_on: string
  days_left: number
}

type Column = 'name' | 'date'

const byName = (a: SignatureRow, b: SignatureRow) =>
  a.company_name.localeCompare(b.company_name, 'ru') || a.expires_on.localeCompare(b.expires_on)
const byDate = (a: SignatureRow, b: SignatureRow) =>
  a.expires_on.localeCompare(b.expires_on) || a.company_name.localeCompare(b.company_name, 'ru')

function left(days: number): string {
  if (days < 0) return 'срок истёк'
  return days === 0 ? 'истекает сегодня' : `осталось дней: ${days}`
}

/** Сроки электронных подписей всех организаций. */
export default function SignaturesPage() {
  const [params, setParams] = useSearchParams()
  const column: Column = params.get('sort') === 'name' ? 'name' : 'date'
  const reverse = params.get('order') === 'desc'
  const [search, setSearch] = useState('')
  const list = useQuery({
    queryKey: ['signatures', 'all'],
    queryFn: () => api<SignatureRow[]>('/signatures'),
    refetchOnMount: 'always',
  })
  // повторное нажатие на выбранную сортировку меняет порядок
  const sort = (next: Column) =>
    setParams(
      { sort: next, ...(next === column && !reverse ? { order: 'desc' } : {}) },
      { replace: true },
    )
  const wanted = search.trim().toLowerCase()
  const shown = (list.data ?? [])
    .filter((row) => `${row.company_name} ${row.holder}`.toLowerCase().includes(wanted))
    .sort(column === 'name' ? byName : byDate)
  if (reverse) shown.reverse()

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">ЭЦП</h1>
      <Field
        label="Поиск по организации или владельцу"
        type="search"
        value={search}
        onChange={(event) => setSearch(event.target.value)}
      />
      <div role="group" aria-label="Сортировка" className="flex flex-wrap gap-2 text-sm">
        {(
          [
            ['name', 'По названию'],
            ['date', 'По сроку действия'],
          ] as const
        ).map(([key, title]) => (
          <button
            key={key}
            type="button"
            aria-pressed={column === key}
            onClick={() => sort(key)}
            className={`cursor-pointer rounded-lg border px-3 py-2 font-medium ${
              column === key
                ? 'border-blue-600 text-blue-700 dark:text-blue-300'
                : 'border-slate-300 dark:border-slate-600'
            }`}
          >
            {title}
            {column === key && <span aria-hidden="true"> {reverse ? '↓' : '↑'}</span>}
          </button>
        ))}
      </div>
      <ErrorText error={list.error} />
      {list.data && shown.length === 0 && (
        <p className="py-6 text-center text-slate-500 dark:text-slate-400">
          {list.data.length === 0
            ? 'Подписей пока нет. Добавьте их в карточке организации, вкладка «ЭЦП».'
            : 'Ничего не найдено.'}
        </p>
      )}
      <ul className="divide-y divide-slate-100 overflow-hidden rounded-xl border border-slate-200 bg-white empty:hidden dark:divide-slate-800 dark:border-slate-800 dark:bg-slate-900">
        {shown.map((row) => (
          <li key={row.id}>
            <Link
              to={`/companies/${row.company_id}?tab=signatures`}
              className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3 hover:bg-slate-50 dark:hover:bg-slate-800/50"
            >
              <span className="min-w-0 flex-1 basis-48">
                <span className="block font-medium break-words">{row.company_name}</span>
                <span className="block text-sm break-words text-slate-500 dark:text-slate-400">
                  {row.holder}
                </span>
              </span>
              <span
                className={`rounded-lg px-3 py-1 text-sm font-medium tabular-nums ${URGENCY_STYLES[urgencyOf(row.days_left)]}`}
              >
                до {formatDate(row.expires_on)} · {left(row.days_left)}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  )
}
