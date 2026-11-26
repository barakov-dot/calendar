import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router'

import { Badge, Button, Card, ErrorText } from '../../components/ui'
import { api } from '../../lib/api'
import { formatDate } from '../../lib/company'
import { describeSchedule, type Reminder, type ReminderData, toData } from '../../lib/reminders'
import { canEdit } from '../../lib/roles'
import type { User } from '../../lib/types'
import { useRefreshTasks } from '../../lib/useTasks'
import ReminderForm from './ReminderForm'

/** Напоминания компании или, без companyId, все доступные (новые — личные). */
export function ReminderBlock({
  companyId,
  editable,
}: {
  companyId: number | null
  editable: boolean
}) {
  const queryClient = useQueryClient()
  const refreshTasks = useRefreshTasks()
  const [editing, setEditing] = useState<number | 'new' | null>(null)
  const reminders = useQuery({
    queryKey: ['reminders', companyId],
    queryFn: () =>
      api<Reminder[]>(companyId === null ? '/reminders' : `/reminders?company_id=${companyId}`),
    refetchOnMount: 'always',
  })
  const done = () => {
    setEditing(null)
    void queryClient.invalidateQueries({ queryKey: ['reminders'] })
    refreshTasks()
  }
  const save = useMutation({
    mutationFn: ({ id, data }: { id?: number; data: ReminderData }) =>
      api(id ? `/reminders/${id}` : '/reminders', { method: id ? 'PATCH' : 'POST', body: data }),
    onSuccess: done,
  })
  const remove = useMutation({
    mutationFn: (id: number) => api(`/reminders/${id}`, { method: 'DELETE' }),
    onSuccess: done,
  })

  return (
    <Card title="Повторяющиеся напоминания">
      <p className="text-sm text-slate-500 dark:text-slate-400">
        Задачи по напоминаниям появляются на 60 дней вперёд.
      </p>
      <ErrorText error={reminders.error ?? save.error ?? remove.error} />
      {reminders.data?.length === 0 && <p className="text-sm">Напоминаний нет.</p>}
      <ul className="space-y-3">
        {reminders.data?.map((item) =>
          editing === item.id ? (
            <li key={item.id}>
              <ReminderForm
                companyId={item.company_id}
                initial={toData(item)}
                onCancel={() => setEditing(null)}
                onSubmit={(data) => save.mutate({ id: item.id, data })}
              />
            </li>
          ) : (
            <li key={item.id} className="space-y-1 text-sm">
              <div className="font-medium">
                {item.title} {!item.is_active && <Badge kind="warning">выключено</Badge>}
              </div>
              <div className="text-slate-500 dark:text-slate-400">
                {companyId === null &&
                  (item.company_id ? (
                    <Link to={`/companies/${item.company_id}`} className="underline">
                      {item.company_name}
                    </Link>
                  ) : (
                    `Личное (${item.created_by_name})`
                  ))}
                {companyId === null && ' · '}
                {describeSchedule(item.schedule)}
                {item.next_dates.length > 0 &&
                  ` · ближайшие: ${item.next_dates.map(formatDate).join(', ')}`}
              </div>
              {editable && item.editable && (
                <div className="flex gap-2">
                  <Button variant="secondary" onClick={() => setEditing(item.id)}>
                    Изменить
                  </Button>
                  <Button
                    variant="danger"
                    onClick={() => {
                      if (window.confirm(`Удалить напоминание «${item.title}»?`)) {
                        remove.mutate(item.id)
                      }
                    }}
                  >
                    Удалить
                  </Button>
                </div>
              )}
            </li>
          ),
        )}
      </ul>
      {editable &&
        (editing === 'new' ? (
          <ReminderForm
            companyId={companyId}
            onCancel={() => setEditing(null)}
            onSubmit={(data) => save.mutate({ data })}
          />
        ) : (
          <Button variant="secondary" onClick={() => setEditing('new')}>
            {companyId === null ? 'Добавить личное напоминание' : 'Добавить напоминание'}
          </Button>
        ))}
    </Card>
  )
}

export default function Reminders({ user }: { user: User }) {
  return <ReminderBlock companyId={null} editable={canEdit(user.role)} />
}
