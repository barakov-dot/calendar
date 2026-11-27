import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'

import TelegramLink from '../../components/TelegramLink'
import { Alert, Badge, Button, Card, Checkbox, ErrorText, Field } from '../../components/ui'
import { api } from '../../lib/api'
import { formatDate } from '../../lib/company'
import { formatDateTime, fullName } from '../../lib/format'
import { type PersonCard, personProblems } from '../../lib/people'
import { ROLE_NAMES } from '../../lib/roles'
import { userTarget } from '../../lib/telegramLinks'

type Company = PersonCard['companies'][number]

function NameForm({
  person,
  onSave,
  pending,
}: {
  person: PersonCard
  onSave: (body: Record<string, unknown>) => void
  pending: boolean
}) {
  const [first, setFirst] = useState(person.first_name)
  const [last, setLast] = useState(person.last_name)
  const unchanged = first.trim() === person.first_name && last.trim() === person.last_name
  return (
    <Card title="Имя">
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Имя" value={first} onChange={(event) => setFirst(event.target.value)} />
        <Field label="Фамилия" value={last} onChange={(event) => setLast(event.target.value)} />
      </div>
      <p className="text-sm text-slate-500 dark:text-slate-400">
        {person.name_overridden
          ? 'Имя задано вами и не меняется, даже если пользователь переименуется в Telegram.'
          : 'Сейчас имя берётся из Telegram. После изменения здесь останется ваше.'}
      </p>
      <div className="flex flex-wrap gap-2">
        <Button
          disabled={unchanged || (!first.trim() && !last.trim()) || pending}
          onClick={() => onSave({ first_name: first, last_name: last })}
        >
          Сохранить имя
        </Button>
        {person.name_overridden && (
          <Button variant="secondary" disabled={pending} onClick={() => onSave({ reset_name: true })}>
            Снова брать из Telegram
          </Button>
        )}
      </div>
    </Card>
  )
}

function ClientCompany({
  userId,
  company,
  onChanged,
}: {
  userId: number
  company: Company
  onChanged: () => void
}) {
  const update = useMutation({
    mutationFn: (patch: Record<string, boolean>) =>
      api(`/companies/${company.id}/members/${userId}`, { method: 'PATCH', body: patch }),
    onSettled: onChanged,
  })
  return (
    <>
      <Checkbox
        label="Клиент платит сам"
        checked={!!company.can_mark_paid}
        disabled={update.isPending || company.is_archived}
        onChange={(can_mark_paid) => update.mutate({ can_mark_paid })}
      />
      <Checkbox
        label="Получает напоминания"
        checked={!!company.receive_reminders}
        disabled={update.isPending || company.is_archived}
        onChange={(receive_reminders) => update.mutate({ receive_reminders })}
      />
      <ErrorText error={update.error} />
    </>
  )
}

export default function UserCard() {
  const { id } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const key = ['user', id]
  const user = useQuery({
    queryKey: key,
    queryFn: () => api<PersonCard>(`/admin/users/${id}`),
    refetchOnMount: 'always',
  })
  const changed = () => void queryClient.invalidateQueries()
  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api<PersonCard>(`/admin/users/${id}`, { method: 'PATCH', body }),
    onSuccess: (data) => {
      queryClient.setQueryData(key, data)
      changed()
    },
  })

  const person = user.data
  if (!person) {
    return user.error ? <ErrorText error={user.error} /> : <p>Загрузка…</p>
  }
  const client = person.role === 'client'
  const problems = personProblems(person)

  return (
    <div className="space-y-4">
      <Link to="/users" className="text-sm text-blue-700 underline dark:text-blue-300">
        ← Все пользователи
      </Link>
      <div className="grid items-start gap-4 lg:grid-cols-2">
        <Card title={fullName(person)}>
          <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 text-sm">
            <dt className="text-slate-500 dark:text-slate-400">Роль</dt>
            <dd>{ROLE_NAMES[person.role]}</dd>
            <dt className="text-slate-500 dark:text-slate-400">Telegram</dt>
            <dd className="break-all">
              {person.username ? (
                <TelegramLink
                  to={userTarget(person.username)}
                  className="text-blue-700 underline dark:text-blue-300"
                >
                  @{person.username}
                </TelegramLink>
              ) : (
                'без имени пользователя'
              )}
            </dd>
            <dt className="text-slate-500 dark:text-slate-400">Telegram ID</dt>
            <dd>{person.telegram_id}</dd>
            <dt className="text-slate-500 dark:text-slate-400">Добавлен</dt>
            <dd>{formatDateTime(person.created_at)}</dd>
            <dt className="text-slate-500 dark:text-slate-400">Согласие на обработку ПДн</dt>
            <dd>{person.pd_consent_at ? formatDateTime(person.pd_consent_at) : 'нет'}</dd>
          </dl>
          <div className="flex flex-wrap gap-1">
            {problems.map((problem) => (
              <Badge key={problem} kind="warning">
                {problem}
              </Badge>
            ))}
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              variant="secondary"
              onClick={() => navigate(`/broadcasts?users=${person.id}`)}
            >
              Написать сообщение
            </Button>
            {person.role !== 'admin' && (
              <Button
                variant={person.is_active ? 'danger' : 'secondary'}
                disabled={save.isPending}
                onClick={() => {
                  if (
                    !person.is_active ||
                    window.confirm(`Отключить доступ: ${fullName(person)}?`)
                  ) {
                    save.mutate({ is_active: !person.is_active })
                  }
                }}
              >
                {person.is_active ? 'Отключить доступ' : 'Включить доступ'}
              </Button>
            )}
          </div>
        </Card>
        <NameForm
          // после сохранения поля заполняются заново
          key={`${person.first_name}|${person.last_name}`}
          person={person}
          pending={save.isPending}
          onSave={(body) => save.mutate(body)}
        />
      </div>
      <ErrorText error={save.error} />
      {save.isSuccess && <Alert kind="success">Сохранено.</Alert>}
      <Card title={`Организации · ${person.companies.length}`}>
        {person.companies.length === 0 && (
          <p className="text-sm">
            {client ? 'Не привязан ни к одной организации.' : 'Закреплённых организаций нет.'}
          </p>
        )}
        <ul className="divide-y divide-slate-200 dark:divide-slate-700">
          {person.companies.map((company) => (
            <li key={company.id} className="space-y-2 py-2">
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <Link
                  to={`/companies/${company.id}`}
                  className="font-medium text-blue-700 underline dark:text-blue-300"
                >
                  {company.name}
                </Link>
                {company.is_primary && <Badge>основной контакт</Badge>}
                {company.is_archived && <Badge kind="warning">в архиве</Badge>}
              </div>
              {client && (
                <ClientCompany userId={person.id} company={company} onChanged={changed} />
              )}
            </li>
          ))}
        </ul>
      </Card>
      {person.substitutions.length > 0 && (
        <Card title="Замещения">
          <ul className="space-y-1 text-sm">
            {person.substitutions.map((item) => (
              <li key={item.id}>
                {formatDate(item.date_from)} – {formatDate(item.date_to)}:{' '}
                {item.substitute_name} замещает: {item.accountant_name}
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  )
}
