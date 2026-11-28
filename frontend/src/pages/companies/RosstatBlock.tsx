import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router'

import { Alert, Button, Card, ErrorText } from '../../components/ui'
import { api } from '../../lib/api'
import { formatDateTime } from '../../lib/format'
import { STATUS_NAMES, type TaskStatus } from '../../lib/tasks'
import { useRefreshTasks } from '../../lib/useTasks'

export interface RosstatData {
  enabled: boolean
  okpo: string
  checked_at: string | null
  error: string
  forms: {
    id: number
    index: string
    name: string
    okud: string
    periodicity: string
    period: string
    deadline: string
    comment: string
    task_id: number | null
    status: TaskStatus | null
  }[]
}

/** Формы статистики, которые организация должна сдать по перечню Росстата. */
export default function RosstatBlock({
  companyId,
  editable,
}: {
  companyId: number
  editable: boolean
}) {
  const queryClient = useQueryClient()
  const refreshTasks = useRefreshTasks()
  const key = ['rosstat', companyId]
  const path = `/companies/${companyId}/rosstat`
  const query = useQuery({
    queryKey: key,
    queryFn: () => api<RosstatData>(path),
    refetchOnMount: 'always',
  })
  const search = useMutation({
    mutationFn: () => api<RosstatData>(`${path}/refresh`, { method: 'POST' }),
    onSuccess: (data) => {
      queryClient.setQueryData(key, data)
      refreshTasks()
    },
    onError: () => void queryClient.invalidateQueries({ queryKey: key }),
  })
  const data = query.data

  return (
    <Card title="Формы Росстата">
      <ErrorText error={query.error} />
      {data && !data.enabled && (
        <Alert kind="warning">
          Поиск форм выключен. Администратор включает его в «Настройках сервиса», вкладка
          «Росстат».
        </Alert>
      )}
      {data && (
        <p className="text-sm text-slate-500 dark:text-slate-400">
          {data.checked_at
            ? `Проверено ${formatDateTime(data.checked_at)}`
            : 'Ещё не проверялось'}
          {data.okpo && ` · ОКПО ${data.okpo}`}
        </p>
      )}
      {editable && data?.enabled && (
        <Button variant="secondary" disabled={search.isPending} onClick={() => search.mutate()}>
          {search.isPending ? 'Ищем…' : 'Проверить сейчас'}
        </Button>
      )}
      <ErrorText error={search.error} />
      {data?.error && !search.error && <Alert kind="error">{data.error}</Alert>}
      {data?.checked_at && !data.error && data.forms.length === 0 && (
        <p className="text-sm">По перечню Росстата форм нет.</p>
      )}
      <ul className="divide-y divide-slate-200 dark:divide-slate-700">
        {data?.forms.map((form) => (
          <li key={form.id} className="space-y-1 py-3 text-sm">
            <p className="font-semibold break-words">
              {form.index || form.okud}
              {form.period && <span className="font-normal"> · {form.period}</span>}
            </p>
            <p className="break-words">{form.name}</p>
            <p>
              Срок сдачи: <strong>{form.deadline || 'не указан'}</strong>
              {form.status && ` · ${STATUS_NAMES[form.status]}`}
            </p>
            <p className="text-slate-500 dark:text-slate-400">
              {[form.periodicity, form.okud && `ОКУД ${form.okud}`].filter(Boolean).join(' · ')}
            </p>
            {form.comment && <p className="break-words">{form.comment}</p>}
            {form.task_id && (
              <Link to={`/tasks/${form.task_id}`} className="text-blue-600 underline">
                Открыть задачу
              </Link>
            )}
          </li>
        ))}
      </ul>
    </Card>
  )
}
