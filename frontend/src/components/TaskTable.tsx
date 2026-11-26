import { useState } from 'react'
import { Link } from 'react-router'

import { formatDate, formatKopecks } from '../lib/company'
import { KIND_NAMES, STATUS_NAMES, type Task, type TaskStatus, toneOf } from '../lib/tasks'
import { TONE_STYLES } from '../lib/toneStyles'
import { useBulkStatus } from '../lib/useTasks'
import { Alert, Button, ErrorText } from './ui'

const BULK: [TaskStatus, string][] = [
  ['paid', 'Оплачено'],
  ['done', 'Сдано'],
  ['not_required', 'Не требуется'],
  ['planned', 'Вернуть в план'],
]

function Amount({ task }: { task: Task }) {
  if (task.amount_kopecks != null) return <>{formatKopecks(task.amount_kopecks)}</>
  if (task.needs_amount && task.status === 'planned') {
    return <span className="text-xs text-amber-700 dark:text-amber-300">нет суммы</span>
  }
  return null
}

/** Список задач. С editable — выбор и массовая смена статуса. */
export default function TaskTable({
  tasks,
  today,
  editable,
  showCompany = true,
}: {
  tasks: Task[]
  today: string
  editable: boolean
  showCompany?: boolean
}) {
  const [selected, setSelected] = useState<ReadonlySet<number>>(new Set())
  const bulk = useBulkStatus(() => setSelected(new Set()))
  // выбранными считаются только задачи, которые сейчас видны
  const chosen = tasks.filter((task) => selected.has(task.id)).map((task) => task.id)

  const toggle = (id: number) => {
    const next = new Set(selected)
    if (!next.delete(id)) next.add(id)
    setSelected(next)
  }

  if (tasks.length === 0) return <p className="text-sm">Задач нет.</p>

  return (
    // раскладка строк зависит от ширины самого списка, а не экрана
    <div className="@container space-y-2">
      {editable && (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              className="size-4"
              checked={chosen.length === tasks.length}
              onChange={() =>
                setSelected(
                  chosen.length === tasks.length ? new Set() : new Set(tasks.map((t) => t.id)),
                )
              }
            />
            Выбрать все ({tasks.length})
          </label>
          {chosen.length > 0 &&
            BULK.map(([status, title]) => (
              <Button
                key={status}
                variant="secondary"
                disabled={bulk.isPending}
                onClick={() => {
                  if (window.confirm(`${title}: задач — ${chosen.length}. Применить?`)) {
                    bulk.mutate({ ids: chosen.slice(0, 1000), status })
                  }
                }}
              >
                {title}
              </Button>
            ))}
        </div>
      )}
      <ErrorText error={bulk.error} />
      {bulk.data && (
        <Alert kind="success">
          Изменено: {bulk.data.updated}.
          {bulk.data.skipped > 0 && ` Пропущено (статус не подходит): ${bulk.data.skipped}.`}
        </Alert>
      )}
      <ul className="divide-y divide-slate-100 dark:divide-slate-800">
        {tasks.map((task) => (
          <li
            key={task.id}
            className="flex items-start gap-3 rounded-md py-2 hover:bg-slate-50 @xl:items-center dark:hover:bg-slate-800/50"
          >
            {editable && (
              <input
                type="checkbox"
                className="mt-1 size-4 @xl:mt-0"
                aria-label={`Выбрать: ${task.title}, ${task.company_name}`}
                checked={selected.has(task.id)}
                onChange={() => toggle(task.id)}
              />
            )}
            <Link
              to={`/tasks/${task.id}`}
              className="min-w-0 flex-1 @xl:grid @xl:grid-cols-[5.5rem_minmax(0,1fr)_auto] @xl:items-center @xl:gap-3"
            >
              <span className="hidden text-sm tabular-nums @xl:block">
                {formatDate(task.due_date)}
              </span>
              <span className="min-w-0">
                <span className="block text-sm font-medium break-words">{task.title}</span>
                <span className="block text-xs text-slate-500 dark:text-slate-400">
                  <span className="@xl:hidden">{formatDate(task.due_date)} · </span>
                  {showCompany && `${task.company_name} · `}
                  {KIND_NAMES[task.kind]}
                </span>
              </span>
              <span className="hidden text-right text-sm tabular-nums @xl:block">
                <Amount task={task} />
              </span>
            </Link>
            <span className="flex flex-col items-end gap-1 text-sm whitespace-nowrap @xl:w-32">
              <span
                className={`rounded-full px-2 py-0.5 text-xs ${TONE_STYLES[toneOf(task, today)]}`}
              >
                {toneOf(task, today) === 'overdue' ? 'Просрочено' : STATUS_NAMES[task.status]}
              </span>
              <span className="@xl:hidden">
                <Amount task={task} />
              </span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}
