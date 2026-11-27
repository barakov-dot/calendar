import { useMutation } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link } from 'react-router'

import { api } from '../lib/api'
import { formatKopecks } from '../lib/company'
import {
  dayTitle,
  KIND_NAMES,
  relativeDay,
  STATUS_NAMES,
  type Task,
  type TaskStatus,
  tasksWord,
} from '../lib/tasks'
import { useRefreshTasks } from '../lib/useTasks'
import { ChevronIcon } from './Icons'
import { Button, ErrorText } from './ui'

const PAGE = 200
/** Столько задач сервер меняет за один запрос. */
const BULK_LIMIT = 1000

interface Change {
  id: number
  from: TaskStatus
  to: TaskStatus
}

const closing = (task: Task): TaskStatus => (task.kind === 'payment' ? 'paid' : 'done')

/** Отметка задач с возможностью отменить последнее действие. */
function useMarking() {
  const refresh = useRefreshTasks()
  const [last, setLast] = useState<Change[] | null>(null)
  const change = useMutation({
    mutationFn: async ({ changes }: { changes: Change[]; undo: boolean }) => {
      for (const status of new Set(changes.map((item) => item.to))) {
        const ids = changes.filter((item) => item.to === status).map((item) => item.id)
        for (let start = 0; start < ids.length; start += BULK_LIMIT) {
          await api('/tasks/bulk', {
            method: 'POST',
            body: { ids: ids.slice(start, start + BULK_LIMIT), status },
          })
        }
      }
    },
    onSuccess: (_, { changes, undo }) => setLast(undo ? null : changes),
    onSettled: refresh,
  })

  useEffect(() => {
    if (!last) return
    const timer = setTimeout(() => setLast(null), 10_000)
    return () => clearTimeout(timer)
  }, [last])

  return {
    pending: change.isPending,
    error: change.error,
    last,
    apply: (changes: Change[]) => change.mutate({ changes, undo: false }),
    undo: () =>
      last &&
      change.mutate({
        changes: last.map(({ id, from, to }) => ({ id, from: to, to: from })),
        undo: true,
      }),
  }
}

function Mark({
  task,
  disabled,
  onClick,
}: {
  task: Task
  disabled: boolean
  onClick: () => void
}) {
  const open = task.status === 'planned'
  const label = open
    ? `Отметить «${STATUS_NAMES[closing(task)]}»`
    : 'Вернуть в план'
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={!open}
      aria-label={`${label}: ${task.title}, ${task.company_name}`}
      title={label}
      disabled={disabled}
      onClick={onClick}
      // крупная область нажатия вокруг небольшого квадрата
      className="group flex shrink-0 cursor-pointer items-center self-stretch pr-1 pl-3 disabled:cursor-wait"
    >
      <span
        className={`flex size-6 items-center justify-center rounded-md border-2 text-sm font-bold ${
          open
            ? 'border-slate-300 text-transparent group-hover:border-blue-600 group-hover:text-blue-600 dark:border-slate-600'
            : task.status === 'not_required'
              ? 'border-slate-400 bg-slate-400 text-white'
              : 'border-green-600 bg-green-600 text-white'
        }`}
      >
        {task.status === 'not_required' ? '–' : '✓'}
      </span>
    </button>
  )
}

function Row({
  task,
  today,
  editable,
  pending,
  onMark,
}: {
  task: Task
  today: string
  editable: boolean
  pending: boolean
  onMark: () => void
}) {
  const open = task.status === 'planned'
  const overdue = open && task.due_date < today
  const details = [
    task.period_label || KIND_NAMES[task.kind],
    task.company_name,
    open ? '' : STATUS_NAMES[task.status],
  ].filter(Boolean)
  const amount =
    task.amount_kopecks != null
      ? formatKopecks(task.amount_kopecks)
      : task.needs_amount && open && (
          <span className="text-xs text-amber-700 dark:text-amber-300">нет суммы</span>
        )
  return (
    <li className="flex items-center">
      {editable && <Mark task={task} disabled={pending} onClick={onMark} />}
      <Link
        to={`/tasks/${task.id}`}
        className="flex min-w-0 flex-1 items-center gap-2 py-3 pr-2 pl-3 hover:bg-slate-50 dark:hover:bg-slate-800/50"
      >
        <span className="min-w-0 flex-1">
          <span
            className={`block font-medium break-words ${open ? '' : 'text-slate-500 line-through dark:text-slate-400'}`}
          >
            {task.action_title || task.title}
            {task.has_files && (
              <span title="Есть файл" aria-label="Есть файл">
                {' '}
                📎
              </span>
            )}
          </span>
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-slate-500 dark:text-slate-400">
            <span className="break-words">{details.join(' · ')}</span>
            {amount && <span className="tabular-nums sm:hidden">{amount}</span>}
            {overdue && (
              <span className="rounded-md bg-red-100 px-2 text-xs font-medium whitespace-nowrap text-red-700 dark:bg-red-950 dark:text-red-300">
                {relativeDay(task.due_date, today)}
              </span>
            )}
          </span>
        </span>
        <span className="hidden shrink-0 text-right text-sm tabular-nums sm:block">{amount}</span>
        <ChevronIcon className="size-5 shrink-0 text-slate-400" />
      </Link>
    </li>
  )
}

const LIST =
  'divide-y divide-slate-100 overflow-hidden rounded-xl border border-slate-200 bg-white dark:divide-slate-800 dark:border-slate-800 dark:bg-slate-900'

/** Лента задач: сначала прошедшие сроки, затем по дням. */
export default function TaskFeed({
  tasks,
  today,
  editable,
  newestFirst = false,
}: {
  tasks: Task[]
  today: string
  editable: boolean
  newestFirst?: boolean
}) {
  const marking = useMarking()
  const [limit, setLimit] = useState(PAGE)
  const overdue = tasks.filter((task) => task.status === 'planned' && task.due_date < today)
  const rest = tasks.filter((task) => !(task.status === 'planned' && task.due_date < today))
  if (newestFirst) rest.reverse()
  const shown = rest.slice(0, Math.max(0, limit - overdue.length))
  const days = [...new Set(shown.map((task) => task.due_date))]
  const hidden = rest.length - shown.length

  const mark = (task: Task) =>
    marking.apply([
      {
        id: task.id,
        from: task.status,
        to: task.status === 'planned' ? closing(task) : 'planned',
      },
    ])
  const markOverdue = () => {
    const question = `Отметить все с прошедшим сроком (${overdue.length})? Платежи — «Оплачено», остальное — «Сдано».`
    if (window.confirm(question)) {
      marking.apply(overdue.map((task) => ({ id: task.id, from: task.status, to: closing(task) })))
    }
  }
  const row = (task: Task) => (
    <Row
      key={task.id}
      task={task}
      today={today}
      editable={editable}
      pending={marking.pending}
      onMark={() => mark(task)}
    />
  )

  return (
    <div className="space-y-5">
      <ErrorText error={marking.error} />
      {tasks.length === 0 && (
        <p className="py-6 text-center text-slate-500 dark:text-slate-400">Задач нет.</p>
      )}
      {overdue.length > 0 && (
        <section id="overdue" className="scroll-mt-4 space-y-2">
          <div className="flex items-baseline gap-2 px-1">
            <h2 className="font-semibold text-red-700 dark:text-red-400">Срок прошёл</h2>
            <span className="text-sm text-slate-500 dark:text-slate-400">
              {overdue.length} {tasksWord(overdue.length)}
            </span>
            {editable && (
              <button
                type="button"
                disabled={marking.pending}
                onClick={markOverdue}
                className="ml-auto cursor-pointer text-sm font-semibold text-blue-700 disabled:opacity-50 dark:text-blue-300"
              >
                Отметить все
              </button>
            )}
          </div>
          <ul className={LIST}>{overdue.slice(0, limit).map(row)}</ul>
        </section>
      )}
      {days.map((date) => (
        <section key={date} className="space-y-2">
          <div className="flex items-baseline gap-2 px-1">
            <h2 className="font-semibold">{dayTitle(date, today)}</h2>
            <span className="text-sm text-slate-500 dark:text-slate-400">
              {relativeDay(date, today)}
            </span>
          </div>
          <ul className={LIST}>{shown.filter((task) => task.due_date === date).map(row)}</ul>
        </section>
      ))}
      {(hidden > 0 || overdue.length > limit) && (
        <div className="text-center">
          <Button variant="secondary" onClick={() => setLimit(limit + PAGE)}>
            Показать ещё
          </Button>
        </div>
      )}
      {marking.last && (
        <div
          role="status"
          className="fixed bottom-24 left-3 z-30 flex items-center gap-3 rounded-xl bg-slate-900 px-4 py-3 text-sm text-white shadow-lg lg:bottom-6 lg:left-64 dark:bg-slate-100 dark:text-slate-900"
        >
          <span>
            Отмечено: {marking.last.length} {tasksWord(marking.last.length)}
          </span>
          <button
            type="button"
            disabled={marking.pending}
            onClick={marking.undo}
            className="cursor-pointer font-semibold text-blue-300 disabled:opacity-50 dark:text-blue-700"
          >
            Отменить
          </button>
        </div>
      )}
    </div>
  )
}
