import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router'

import { Card, ErrorText } from '../../components/ui'
import { api } from '../../lib/api'
import { type Task, todayIso } from '../../lib/tasks'
import ClientTasks from './ClientTasks'

/** Задача по ссылке из сообщения бота. */
export default function ClientTaskPage() {
  const id = Number(useParams().id)
  // ключ начинается с 'task', поэтому обновляется после отметки оплаты
  const task = useQuery({
    queryKey: ['task', id],
    queryFn: () => api<Task>(`/tasks/${id}`),
    refetchOnMount: 'always',
  })

  return (
    <div className="space-y-4">
      <Link to="/" className="text-sm text-blue-600 underline">
        ← Платежи
      </Link>
      <ErrorText error={task.error} />
      {task.data && (
        <Card>
          <ClientTasks tasks={[task.data]} today={todayIso()} />
          {task.data.source_ref && (
            <p className="text-sm text-slate-500 dark:text-slate-400">
              Основание: {task.data.source_ref}
            </p>
          )}
        </Card>
      )}
    </div>
  )
}
