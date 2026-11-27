import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { Badge, Button, Card, Checkbox, ErrorText, Field } from '../../components/ui'
import { api } from '../../lib/api'
import { formatDate } from '../../lib/company'
import { useRefreshTasks } from '../../lib/useTasks'

export interface Signature {
  id: number
  holder: string
  expires_on: string
  notify_client: boolean
  days_left: number
}

type Form = Pick<Signature, 'holder' | 'expires_on' | 'notify_client'>

const EMPTY: Form = { holder: '', expires_on: '', notify_client: false }

/** Электронные подписи компании и сроки их действия. */
export default function SignaturesBlock({
  companyId,
  editable,
}: {
  companyId: number
  editable: boolean
}) {
  const base = `/companies/${companyId}/signatures`
  const key = ['signatures', companyId]
  const queryClient = useQueryClient()
  const refresh = useRefreshTasks()
  const list = useQuery({ queryKey: key, queryFn: () => api<Signature[]>(base) })
  // id редактируемой подписи, 'new' — добавление
  const [editing, setEditing] = useState<number | 'new' | null>(null)
  const changed = () => {
    setEditing(null)
    void queryClient.invalidateQueries({ queryKey: key })
    refresh()
  }
  const save = useMutation({
    mutationFn: (body: Form) =>
      typeof editing === 'number'
        ? api(`${base}/${editing}`, { method: 'PATCH', body })
        : api(base, { method: 'POST', body }),
    onSuccess: changed,
  })
  const remove = useMutation({
    mutationFn: (id: number) => api(`${base}/${id}`, { method: 'DELETE' }),
    onSuccess: changed,
  })
  const form = (initial: Form) => (
    <SignatureForm
      initial={initial}
      busy={save.isPending}
      onCancel={() => setEditing(null)}
      onSubmit={(body) => save.mutate(body)}
    />
  )

  return (
    <Card title="Электронные подписи">
      <p className="text-sm text-slate-500 dark:text-slate-400">
        Срок подписи появится в календаре, а напоминания придут бухгалтеру заранее.
      </p>
      <ErrorText error={list.error ?? save.error ?? remove.error} />
      {list.data?.length === 0 && <p className="text-sm">Подписей нет.</p>}
      <ul className="divide-y divide-slate-200 dark:divide-slate-700">
        {list.data?.map((item) =>
          editing === item.id ? (
            <li key={item.id} className="py-2">
              {form({
                holder: item.holder,
                expires_on: item.expires_on,
                notify_client: item.notify_client,
              })}
            </li>
          ) : (
            <li key={item.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <span className="text-sm">
                <span className="font-medium">{item.holder}</span> — до{' '}
                {formatDate(item.expires_on)}{' '}
                <Badge kind={item.days_left <= 30 ? 'warning' : 'info'}>
                  {item.days_left < 0 ? 'срок истёк' : `осталось дней: ${item.days_left}`}
                </Badge>
                {item.notify_client && <span className="text-slate-500"> · клиент получает напоминания</span>}
              </span>
              {editable && (
                <span className="flex gap-2">
                  <Button variant="secondary" onClick={() => setEditing(item.id)}>
                    Изменить
                  </Button>
                  <Button
                    variant="danger"
                    onClick={() => {
                      if (window.confirm('Удалить подпись и напоминания о ней?')) {
                        remove.mutate(item.id)
                      }
                    }}
                  >
                    Удалить
                  </Button>
                </span>
              )}
            </li>
          ),
        )}
      </ul>
      {editable &&
        (editing === 'new' ? (
          form(EMPTY)
        ) : (
          <Button variant="secondary" onClick={() => setEditing('new')}>
            Добавить подпись
          </Button>
        ))}
    </Card>
  )
}

function SignatureForm({
  initial,
  busy,
  onSubmit,
  onCancel,
}: {
  initial: Form
  busy: boolean
  onSubmit: (form: Form) => void
  onCancel: () => void
}) {
  const [form, setForm] = useState(initial)
  const change = (patch: Partial<Form>) => setForm({ ...form, ...patch })

  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-[1fr_12rem]">
        <Field
          label="Чья подпись"
          value={form.holder}
          maxLength={200}
          onChange={(event) => change({ holder: event.target.value })}
        />
        <Field
          label="Действует до"
          type="date"
          value={form.expires_on}
          onChange={(event) => change({ expires_on: event.target.value })}
        />
      </div>
      <Checkbox
        label="Напоминать и клиенту"
        checked={form.notify_client}
        onChange={(notify_client) => change({ notify_client })}
      />
      <div className="flex gap-2">
        <Button
          disabled={!form.holder.trim() || !form.expires_on || busy}
          onClick={() => onSubmit(form)}
        >
          Сохранить подпись
        </Button>
        <Button variant="secondary" onClick={onCancel}>
          Отмена
        </Button>
      </div>
    </div>
  )
}
