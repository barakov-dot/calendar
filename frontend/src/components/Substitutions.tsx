import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { api } from '../lib/api'
import { formatDate } from '../lib/company'
import type { Substitution } from '../lib/substitutions'
import { todayIso } from '../lib/tasks'
import { useStaff } from '../pages/companies/useStaff'
import { Alert, Button, Card, ErrorText, Field, Select } from './ui'

/** Напоминание на главной странице: кого заменяю я и кто заменяет меня. */
export function SubstitutionNotice({ userId }: { userId: number }) {
  const mine = useQuery({
    queryKey: ['substitutions', 'mine'],
    queryFn: () => api<Substitution[]>('/me/substitutions'),
  })
  const active = Array.isArray(mine.data) ? mine.data.filter((item) => item.active) : []

  return (
    <>
      {active.map((item) => (
        <Alert key={item.id}>
          {item.substitute_id === userId
            ? `Вы замещаете: ${item.accountant_name}`
            : `Вас замещает: ${item.substitute_name}`}{' '}
          до {formatDate(item.date_to)} включительно.
        </Alert>
      ))}
    </>
  )
}

/** Управление замещениями (администратор). */
export function SubstitutionsCard() {
  const queryClient = useQueryClient()
  const staff = useStaff(true)
  const list = useQuery({
    queryKey: ['substitutions', 'all'],
    queryFn: () => api<Substitution[]>('/admin/substitutions'),
  })
  const reload = () => queryClient.invalidateQueries({ queryKey: ['substitutions'] })
  const empty = { accountant_id: 0, substitute_id: 0, date_from: todayIso(), date_to: '' }
  const [form, setForm] = useState(empty)
  const change = (patch: Partial<typeof form>) => setForm({ ...form, ...patch })
  const add = useMutation({
    mutationFn: () => api('/admin/substitutions', { method: 'POST', body: form }),
    onSuccess: () => {
      setForm(empty)
      void reload()
    },
  })
  const remove = useMutation({
    mutationFn: (id: number) => api(`/admin/substitutions/${id}`, { method: 'DELETE' }),
    onSettled: reload,
  })
  const ready =
    form.accountant_id > 0 &&
    form.substitute_id > 0 &&
    form.accountant_id !== form.substitute_id &&
    form.date_from !== '' &&
    form.date_to >= form.date_from

  const people = (label: string, name: 'accountant_id' | 'substitute_id') => (
    <Select
      label={label}
      value={form[name]}
      onChange={(event) => change({ [name]: Number(event.target.value) })}
    >
      <option value={0}>Выберите</option>
      {staff.data?.filter((member) => member.role !== 'assistant').map((member) => (
        <option key={member.id} value={member.id}>
          {member.name}
        </option>
      ))}
    </Select>
  )

  return (
    <Card title="Замещения">
      <p className="text-sm text-slate-500 dark:text-slate-400">
        В эти дни замещающий видит и ведёт компании бухгалтера и получает вместо него
        уведомления.
      </p>
      <ErrorText error={list.error ?? staff.error ?? remove.error} />
      <ul className="divide-y divide-slate-200 text-sm dark:divide-slate-700">
        {list.data?.map((item) => (
          <li key={item.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
            <span>
              {item.accountant_name} → {item.substitute_name}, {formatDate(item.date_from)} —{' '}
              {formatDate(item.date_to)}
              {item.active && <span className="text-green-700 dark:text-green-400"> · идёт</span>}
            </span>
            <Button
              variant="danger"
              onClick={() => {
                if (window.confirm('Отменить замещение?')) remove.mutate(item.id)
              }}
            >
              Отменить
            </Button>
          </li>
        ))}
      </ul>
      <div className="grid gap-3 sm:grid-cols-2">
        {people('Кого замещают', 'accountant_id')}
        {people('Кто замещает', 'substitute_id')}
        <Field
          label="С"
          type="date"
          value={form.date_from}
          onChange={(event) => change({ date_from: event.target.value })}
        />
        <Field
          label="По (включительно)"
          type="date"
          value={form.date_to}
          onChange={(event) => change({ date_to: event.target.value })}
        />
      </div>
      <ErrorText error={add.error} />
      <Button disabled={!ready || add.isPending} onClick={() => add.mutate()}>
        Назначить замещение
      </Button>
    </Card>
  )
}
