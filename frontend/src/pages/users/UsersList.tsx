import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'

import { Badge, Button, Card, ErrorText, Field, Select } from '../../components/ui'
import { api } from '../../lib/api'
import { fullName } from '../../lib/format'
import { type Person, personProblems } from '../../lib/people'
import { ROLE_NAMES } from '../../lib/roles'

/** Все пользователи сервиса. Только администратору. */
export default function UsersList() {
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const role = params.get('role') ?? ''
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<ReadonlySet<number>>(new Set())
  const users = useQuery({
    queryKey: ['users', role, search],
    queryFn: () => {
      const query = new URLSearchParams({ q: search })
      if (role) query.set('role', role)
      return api<Person[]>(`/admin/users?${query}`)
    },
    placeholderData: keepPreviousData,
    refetchOnMount: 'always',
  })

  const toggle = (id: number) => {
    const next = new Set(selected)
    if (!next.delete(id)) next.add(id)
    setSelected(next)
  }

  return (
    <Card title="Пользователи">
      <div className="grid gap-3 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <Field
          label="Поиск по имени или @username"
          type="search"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <Select
          label="Роль"
          value={role}
          onChange={(event) =>
            setParams(event.target.value ? { role: event.target.value } : {}, { replace: true })
          }
        >
          <option value="">Все роли</option>
          {Object.entries(ROLE_NAMES).map(([key, title]) => (
            <option key={key} value={key}>
              {title}
            </option>
          ))}
        </Select>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button
          disabled={selected.size === 0}
          onClick={() => navigate(`/broadcasts?users=${[...selected].join(',')}`)}
        >
          Написать выбранным{selected.size > 0 && ` (${selected.size})`}
        </Button>
        {selected.size > 0 && (
          <Button variant="secondary" onClick={() => setSelected(new Set())}>
            Снять выбор
          </Button>
        )}
      </div>
      <p className="text-sm text-slate-500 dark:text-slate-400">
        Сотрудников приглашают в разделе <Link to="/accountants" className="underline">«Команда»</Link>
        , клиентов — из карточки организации.
      </p>
      <ErrorText error={users.error} />
      {users.data && (
        <p className="text-sm text-slate-500 dark:text-slate-400">Найдено: {users.data.length}</p>
      )}
      <ul className="divide-y divide-slate-200 dark:divide-slate-700">
        {users.data?.map((person) => (
          <li key={person.id} className="flex items-center gap-3">
            <input
              type="checkbox"
              className="size-4 shrink-0"
              aria-label={`Выбрать: ${fullName(person)}`}
              checked={selected.has(person.id)}
              onChange={() => toggle(person.id)}
            />
            <Link
              to={`/users/${person.id}`}
              className="min-w-0 flex-1 rounded-lg py-2 hover:bg-slate-50 dark:hover:bg-slate-800/50"
            >
              <span className="block text-sm font-medium break-words">{fullName(person)}</span>
              <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-slate-500 dark:text-slate-400">
                {[
                  ROLE_NAMES[person.role],
                  person.username && `@${person.username}`,
                  person.companies_count > 0 && `организаций: ${person.companies_count}`,
                ]
                  .filter(Boolean)
                  .join(' · ')}
                {personProblems(person).map((problem) => (
                  <Badge key={problem} kind="warning">
                    {problem}
                  </Badge>
                ))}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </Card>
  )
}
