import { Link } from 'react-router'

import { formatDate, formatKopecks } from '../../lib/company'
import type { Demand, DemandStep } from '../../lib/demands'
import { relativeDay, todayIso } from '../../lib/tasks'

function Step({ title, step, today }: { title: string; step: DemandStep | null; today: string }) {
  if (!step) return null
  const open = step.status === 'planned'
  const overdue = open && step.due_date < today
  return (
    <span className="flex flex-wrap items-baseline gap-x-2 text-sm">
      <span aria-hidden="true" className={open ? 'text-slate-400' : 'font-bold text-green-600'}>
        {open ? '○' : '✓'}
      </span>
      <span>
        {title}: {formatDate(step.due_date)}
      </span>
      {open && (
        <span
          className={
            overdue
              ? 'font-semibold text-red-700 dark:text-red-400'
              : 'text-slate-500 dark:text-slate-400'
          }
        >
          {relativeDay(step.due_date, today)}
        </span>
      )}
    </span>
  )
}

/** Требования карточками: вид, сумма и два срока. */
export default function DemandCards({
  demands,
  showCompany = true,
}: {
  demands: Demand[]
  showCompany?: boolean
}) {
  const today = todayIso()
  return (
    <ul className="grid gap-3 lg:grid-cols-2">
      {demands.map((item) => (
        <li key={item.id}>
          <Link
            to={`/demands/${item.id}`}
            className="block h-full space-y-1 rounded-xl border border-slate-200 bg-white p-4 hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-900 dark:hover:bg-slate-800/50"
          >
            {showCompany && (
              <span className="block font-semibold break-words">{item.company_name}</span>
            )}
            <span className="block text-sm break-words">
              {item.name}
              {item.number && ` № ${item.number}`} от {formatDate(item.doc_date)}
            </span>
            {item.amount_kopecks != null && (
              <span className="block text-sm font-medium tabular-nums">
                {formatKopecks(item.amount_kopecks)}
              </span>
            )}
            <Step title="Квитанция" step={item.receipt} today={today} />
            <Step title={item.response_label} step={item.response} today={today} />
          </Link>
        </li>
      ))}
    </ul>
  )
}
