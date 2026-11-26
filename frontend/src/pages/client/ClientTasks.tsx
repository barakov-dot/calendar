import { useMutation } from '@tanstack/react-query'
import { Link } from 'react-router'

import { Button, ErrorText } from '../../components/ui'
import { api } from '../../lib/api'
import { formatDate, formatKopecks } from '../../lib/company'
import { clientStatus, type Task, toneOf } from '../../lib/tasks'
import { TONE_STYLES } from '../../lib/toneStyles'
import { useRefreshTasks } from '../../lib/useTasks'

/** Задачи глазами клиента: что, сколько, до какого числа и оплачено ли. */
export default function ClientTasks({ tasks, today }: { tasks: Task[]; today: string }) {
  if (tasks.length === 0) return <p className="text-sm">Ничего нет.</p>
  return (
    <ul className="divide-y divide-slate-200 dark:divide-slate-700">
      {tasks.map((task) => (
        <ClientTask key={task.id} task={task} today={today} />
      ))}
    </ul>
  )
}

function ClientTask({ task, today }: { task: Task; today: string }) {
  const refresh = useRefreshTasks()
  const act = useMutation({
    mutationFn: (action: 'mark-paid' | 'unmark-paid') =>
      api(`/tasks/${task.id}/${action}`, { method: 'POST' }),
    onSettled: refresh,
  })
  const tone = toneOf(task, today)

  return (
    <li className="space-y-2 py-3">
      <Link to={`/tasks/${task.id}`} className="block">
        <span className="block font-medium">
          до {formatDate(task.due_date)}
          {task.amount_kopecks != null && ` — ${formatKopecks(task.amount_kopecks)}`}
        </span>
        <span className="block text-sm break-words">{task.title}</span>
        <span className="block text-sm text-slate-500 dark:text-slate-400">
          {task.company_name}
        </span>
      </Link>
      {task.client_note && <p className="text-sm break-words">{task.client_note}</p>}
      <div className="flex flex-wrap items-center gap-2">
        <span className={`rounded-full px-2 py-0.5 text-xs ${TONE_STYLES[tone]}`}>
          {tone === 'overdue' && task.kind === 'payment' ? 'Срок прошёл' : clientStatus(task)}
        </span>
        {task.can_mark_paid && (
          <Button
            disabled={act.isPending}
            onClick={() => {
              if (window.confirm(`Отметить оплаченным: ${task.title}?`)) act.mutate('mark-paid')
            }}
          >
            Оплатил
          </Button>
        )}
        {task.can_unmark_paid && (
          <Button
            variant="secondary"
            disabled={act.isPending}
            onClick={() => act.mutate('unmark-paid')}
          >
            Отменить отметку
          </Button>
        )}
      </div>
      <ErrorText error={act.error} />
    </li>
  )
}
