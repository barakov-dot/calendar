import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'

import TextArea from '../../components/TextArea'
import { Alert, Button, Card, Checkbox, ErrorText, Field } from '../../components/ui'
import { api } from '../../lib/api'
import { formatDate, formatKopecks, parseRubles, toRublesText } from '../../lib/company'
import { formatDateTime } from '../../lib/format'
import { canEdit, ROLE_NAMES } from '../../lib/roles'
import {
  KIND_NAMES,
  STATUS_NAMES,
  statusesFor,
  type TaskDetail,
  type TaskStatus,
  todayIso,
  toneOf,
} from '../../lib/tasks'
import type { Role, User } from '../../lib/types'
import { useBulkStatus, useRefreshTasks } from '../../lib/useTasks'

export default function TaskPage({ user }: { user: User }) {
  const id = Number(useParams().id)
  const task = useQuery({
    queryKey: ['task', id],
    queryFn: () => api<TaskDetail>(`/tasks/${id}`),
    refetchOnMount: 'always',
  })
  const navigate = useNavigate()

  return (
    <div className="space-y-4">
      <button type="button" onClick={() => navigate(-1)} className="text-sm text-blue-600 underline">
        ← Назад
      </button>
      <ErrorText error={task.error} />
      {task.data && <Loaded key={id} task={task.data} editable={canEdit(user.role)} />}
    </div>
  )
}

function Loaded({ task, editable }: { task: TaskDetail; editable: boolean }) {
  const refresh = useRefreshTasks()
  const navigate = useNavigate()
  const status = useMutation({
    mutationFn: (value: TaskStatus) =>
      api(`/tasks/${task.id}`, { method: 'PATCH', body: { status: value } }),
    onSuccess: refresh,
  })
  const resetDue = useMutation({
    mutationFn: () => api(`/tasks/${task.id}`, { method: 'PATCH', body: { reset_due: true } }),
    onSuccess: refresh,
  })
  const remove = useMutation({
    mutationFn: () => api(`/tasks/${task.id}`, { method: 'DELETE' }),
    onSuccess: () => {
      refresh()
      navigate(-1)
    },
  })
  const overdue = toneOf(task, todayIso()) === 'overdue'
  const deletable = task.source === 'custom' && !task.recurring_reminder_id

  return (
    <>
      <Card title={task.title}>
        <p className="text-sm">
          {task.company_id ? (
            <Link to={`/companies/${task.company_id}`} className="text-blue-600 underline">
              {task.company_name}
            </Link>
          ) : (
            task.company_name
          )}
          {` · ${KIND_NAMES[task.kind]}`}
        </p>
        <p>
          Срок: <strong>{formatDate(task.due_date)}</strong>
          {task.due_date !== task.original_due_date &&
            ` (по закону или расписанию ${formatDate(task.original_due_date)}${task.due_overridden ? ', изменён вручную' : ', перенесён с выходного'})`}
        </p>
        {overdue && <Alert kind="error">Срок прошёл.</Alert>}
        {task.description && <p className="text-sm">{task.description}</p>}
        <p className="text-sm">
          Статус: <strong>{STATUS_NAMES[task.status]}</strong>
          {task.status_changed_at && (
            <span className="text-slate-500 dark:text-slate-400">
              {' — '}
              {task.status_changed_by_role === 'system'
                ? 'выставлен автоматически'
                : `${task.status_changed_by_name} (${ROLE_NAMES[task.status_changed_by_role as Role]})`}
              , {formatDateTime(task.status_changed_at)}
            </span>
          )}
        </p>
        {editable && (
          <div className="flex flex-wrap gap-2">
            {statusesFor(task.kind)
              .filter((value) => value !== task.status)
              .map((value) => (
                <Button
                  key={value}
                  variant={value === 'paid' || value === 'done' ? 'primary' : 'secondary'}
                  disabled={status.isPending}
                  onClick={() => status.mutate(value)}
                >
                  {value === 'planned' ? 'Вернуть в план' : STATUS_NAMES[value]}
                </Button>
              ))}
            {task.due_overridden && (
              <Button variant="secondary" onClick={() => resetDue.mutate()}>
                Вернуть исходный срок
              </Button>
            )}
          </div>
        )}
        <ErrorText error={status.error ?? resetDue.error ?? remove.error} />
      </Card>

      {task.nds_parts.length > 0 && <NdsBlock task={task} editable={editable} />}

      {editable ? (
        <EditForm key={JSON.stringify(editableFields(task))} task={task} />
      ) : (
        <Card title="Сумма и комментарии">
          <p className="text-sm">
            Сумма: {task.amount_kopecks == null ? 'не указана' : formatKopecks(task.amount_kopecks)}
          </p>
          <p className="text-sm">Внутренний комментарий: {task.comment || '—'}</p>
          <p className="text-sm">Комментарий для клиента: {task.client_note || '—'}</p>
          <p className="text-sm">
            Клиент {task.client_visible ? 'видит' : 'не видит'} задачу.
          </p>
        </Card>
      )}

      {editable && deletable && (
        <Button
          variant="danger"
          onClick={() => {
            if (window.confirm('Удалить задачу?')) remove.mutate()
          }}
        >
          Удалить задачу
        </Button>
      )}
      {task.source === 'rule' && (
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Основание: {task.source_ref}. Сроки сформированы автоматически, итоговое решение — за
          бухгалтером.
        </p>
      )}
    </>
  )
}

function editableFields(task: TaskDetail) {
  return {
    title: task.title,
    description: task.description,
    due_date: task.due_date,
    amount: toRublesText(task.amount_kopecks),
    comment: task.comment,
    client_note: task.client_note,
    client_visible: task.client_visible,
  }
}

function EditForm({ task }: { task: TaskDetail }) {
  const initial = editableFields(task)
  const [form, setForm] = useState(initial)
  const refresh = useRefreshTasks()
  const change = (patch: Partial<typeof form>) => setForm({ ...form, ...patch })
  const hasAmount = task.kind === 'payment' || task.kind === 'other'
  const kopecks = parseRubles(form.amount)
  // отправляются только изменённые поля: сумма и срок иначе стали бы «ручными»
  const changed = Object.fromEntries(
    Object.entries(form).filter(([key, value]) => value !== initial[key as keyof typeof form]),
  )
  const body: Record<string, unknown> = { ...changed }
  if ('amount' in body) {
    delete body.amount
    body.amount_kopecks = kopecks
  }
  const save = useMutation({
    mutationFn: () => api(`/tasks/${task.id}`, { method: 'PATCH', body }),
    onSuccess: refresh,
  })

  return (
    <Card title="Изменить">
      {task.source === 'custom' && (
        <>
          <Field label="Название" value={form.title} onChange={(e) => change({ title: e.target.value })} />
          <TextArea label="Описание" value={form.description} onChange={(description) => change({ description })} />
        </>
      )}
      <Field
        label="Срок"
        type="date"
        value={form.due_date}
        onChange={(event) => change({ due_date: event.target.value })}
      />
      {hasAmount && (
        <Field
          label="Сумма, ₽"
          inputMode="decimal"
          value={form.amount}
          hint={task.amount_overridden ? 'Введена вручную: пересчёт НДС её не меняет' : undefined}
          onChange={(event) => change({ amount: event.target.value })}
        />
      )}
      {kopecks === undefined && <Alert kind="error">Сумма — число, например 36 000,50.</Alert>}
      <TextArea
        label="Внутренний комментарий (клиент не видит)"
        value={form.comment}
        onChange={(comment) => change({ comment })}
      />
      <TextArea
        label="Комментарий для клиента"
        value={form.client_note}
        onChange={(client_note) => change({ client_note })}
      />
      {task.company_id !== null && (
        <Checkbox
          label="Клиент видит задачу"
          checked={form.client_visible}
          onChange={(client_visible) => change({ client_visible })}
        />
      )}
      <ErrorText error={save.error} />
      <Button
        disabled={
          Object.keys(changed).length === 0 ||
          kopecks === undefined ||
          !form.due_date ||
          save.isPending
        }
        onClick={() => save.mutate()}
      >
        Сохранить
      </Button>
    </Card>
  )
}

function NdsBlock({ task, editable }: { task: TaskDetail; editable: boolean }) {
  const refresh = useRefreshTasks()
  const [total, setTotal] = useState('')
  const kopecks = parseRubles(total)
  const split = useMutation({
    mutationFn: () =>
      api(`/tasks/nds/${task.company_id}/${task.period_key}`, {
        method: 'PUT',
        body: { amount_kopecks: kopecks },
      }),
    onSuccess: () => {
      setTotal('')
      refresh()
    },
  })
  const payAll = useBulkStatus(() => {})
  const unpaid = task.nds_parts.filter((part) => part.status === 'planned')

  return (
    <Card title="НДС за квартал: три платежа">
      <ul className="text-sm">
        {task.nds_parts.map((part) => (
          <li key={part.id}>
            <Link
              to={`/tasks/${part.id}`}
              replace
              className={part.id === task.id ? 'font-semibold' : 'text-blue-600 underline'}
            >
              Платёж {part.part}
            </Link>
            {` — ${formatDate(part.due_date)}, ${part.amount_kopecks == null ? 'сумма не указана' : formatKopecks(part.amount_kopecks)}, ${STATUS_NAMES[part.status]}`}
            {part.amount_overridden && ' (сумма вручную)'}
          </li>
        ))}
      </ul>
      {editable && (
        <>
          <Field
            label="Сумма НДС за весь квартал, ₽"
            inputMode="decimal"
            value={total}
            hint="Делится на три части. Оплаченные и исправленные вручную не меняются."
            onChange={(event) => setTotal(event.target.value)}
          />
          {kopecks === undefined && <Alert kind="error">Сумма — число, например 36 000,50.</Alert>}
          <div className="flex flex-wrap gap-2">
            <Button disabled={kopecks == null || split.isPending} onClick={() => split.mutate()}>
              Разделить на три платежа
            </Button>
            {unpaid.length > 0 && (
              <Button
                variant="secondary"
                disabled={payAll.isPending}
                onClick={() => {
                  if (window.confirm(`Отметить оплаченными частей: ${unpaid.length}?`)) {
                    payAll.mutate({ ids: unpaid.map((part) => part.id), status: 'paid' })
                  }
                }}
              >
                Отметить все части оплаченными
              </Button>
            )}
          </div>
          <ErrorText error={split.error ?? payAll.error} />
        </>
      )}
    </Card>
  )
}
