import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router'

import { Badge, Card, Checkbox, ErrorText, Field } from '../../components/ui'
import { api } from '../../lib/api'
import { ENTITY_NAMES, REGIME_NAMES } from '../../lib/company'
import { canEdit } from '../../lib/roles'
import type { CompanyListItem, User } from '../../lib/types'
import { attentionReasons } from '../../lib/useCompanies'

/** Тот же кружок, что и число в меню: показывает, какая организация посчитана. */
function AttentionDot({ reasons }: { reasons: string[] }) {
  if (reasons.length === 0) return null
  const text = `Требует внимания: ${reasons.join(', ')}`
  return (
    <span
      role="img"
      aria-label={text}
      title={text}
      className="flex size-5 shrink-0 items-center justify-center rounded-full bg-orange-600 text-xs font-bold text-white"
    >
      !
    </span>
  )
}

export default function CompaniesList({ user }: { user: User }) {
  const [search, setSearch] = useState('')
  const [archived, setArchived] = useState(false)
  const companies = useQuery({
    queryKey: ['companies', archived, search],
    queryFn: () =>
      api<CompanyListItem[]>(
        `/companies?${new URLSearchParams({ archived: String(archived), q: search })}`,
      ),
    placeholderData: keepPreviousData,
    refetchOnMount: 'always',
  })

  return (
    <Card title="Организации">
      {canEdit(user.role) && (
        <Link
          to="/companies/new"
          className="inline-block rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white"
        >
          Добавить организацию
        </Link>
      )}
      <Field
        label="Поиск по названию или ИНН"
        type="search"
        value={search}
        onChange={(event) => setSearch(event.target.value)}
      />
      <Checkbox label="Показать архив" checked={archived} onChange={setArchived} />
      <ErrorText error={companies.error} />
      {companies.data?.length === 0 && (
        <p className="text-sm">
          {user.role === 'assistant' && !search && !archived
            ? 'За вами пока не закреплены организации. Это делает администратор или главный бухгалтер.'
            : 'Ничего не найдено.'}
        </p>
      )}
      <ul className="grid gap-3 lg:grid-cols-2">
        {companies.data?.map((company) => (
          <li key={company.id}>
            <Link
              to={`/companies/${company.id}`}
              className="block h-full space-y-1 rounded-lg border border-slate-200 p-3 hover:border-blue-400 hover:bg-slate-50 dark:border-slate-800 dark:hover:border-blue-700 dark:hover:bg-slate-800/50"
            >
              <div className="flex items-start gap-2">
                <span className="min-w-0 flex-1 font-medium break-words">
                  {company.short_name || company.name}
                </span>
                {!archived && <AttentionDot reasons={attentionReasons(company)} />}
              </div>
              <div className="text-sm text-slate-500 dark:text-slate-400">
                ИНН {company.inn}
                {user.role !== 'accountant' && ` · ${company.accountant_name || 'без бухгалтера'}`}
              </div>
              <div className="flex flex-wrap gap-1">
                <Badge>{ENTITY_NAMES[company.entity_type]}</Badge>
                <Badge>{REGIME_NAMES[company.main_regime]}</Badge>
                {company.nds_payer && <Badge>НДС</Badge>}
                {company.has_employees && <Badge>сотрудники</Badge>}
                {company.patents_count > 0 && <Badge>патентов: {company.patents_count}</Badge>}
                {company.has_missing_amount && <Badge kind="warning">есть задачи без суммы</Badge>}
                {company.members_count === 0 && <Badge kind="warning">нет клиента в боте</Badge>}
                {!archived && !company.has_signature && (
                  <Badge kind="warning">не указан срок ЭЦП</Badge>
                )}
                {company.has_blocked_member && (
                  <Badge kind="warning">клиент заблокировал бота</Badge>
                )}
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </Card>
  )
}
