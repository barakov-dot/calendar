import { useState } from 'react'
import { Link } from 'react-router'

import TaskFilterBar, { type Filters } from '../../components/TaskFilterBar'
import TaskTable from '../../components/TaskTable'
import { Alert, Card, ErrorText } from '../../components/ui'
import { formatDate } from '../../lib/company'
import { canEdit } from '../../lib/roles'
import { addDays, todayIso } from '../../lib/tasks'
import type { User } from '../../lib/types'
import { useTasks } from '../../lib/useTasks'

export default function Today({ user }: { user: User }) {
  const [filters, setFilters] = useState<Filters>({ company_id: '', kind: '', status: 'planned' })
  const today = todayIso()
  const overdue = useTasks({ ...filters, status: 'planned', to: addDays(today, -1) })
  const week = useTasks({ ...filters, from: today, to: addDays(today, 7) })
  const showOverdue = filters.status === 'planned' || filters.status === ''
  const editable = canEdit(user.role)
  const items = week.data?.items ?? []
  const sections = [
    ['Сегодня', items.filter((task) => task.due_date === today)],
    ['Ближайшие 7 дней', items.filter((task) => task.due_date > today)],
  ] as const

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">Сегодня, {formatDate(today)}</h1>
        {editable && (
          <Link
            to="/tasks/new"
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white"
          >
            Добавить задачу
          </Link>
        )}
      </div>
      <TaskFilterBar value={filters} onChange={setFilters} />
      <ErrorText error={overdue.error ?? week.error} />
      {showOverdue && overdue.data && overdue.data.total > 0 && (
        <details className="rounded-xl border border-red-300 bg-white p-4 dark:border-red-900 dark:bg-slate-900" open={overdue.data.total <= 20}>
          <summary className="cursor-pointer text-lg font-semibold text-red-700 dark:text-red-300">
            Просрочено: {overdue.data.total}
          </summary>
          <div className="mt-3 space-y-2">
            {overdue.data.total > overdue.data.items.length && (
              <Alert kind="warning">
                Показаны первые {overdue.data.items.length}. Выберите компанию или тип.
              </Alert>
            )}
            <TaskTable tasks={overdue.data.items} today={today} editable={editable} />
          </div>
        </details>
      )}
      {week.data && (
        <div className="space-y-4">
          {sections.map(([title, tasks]) => (
            <Card key={title} title={`${title} · ${tasks.length}`}>
              <TaskTable tasks={tasks} today={today} editable={editable} />
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
