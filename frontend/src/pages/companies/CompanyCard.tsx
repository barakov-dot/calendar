import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams } from 'react-router'

import { Alert, Button, Card, ErrorText, Select } from '../../components/ui'
import { api } from '../../lib/api'
import { toForm } from '../../lib/company'
import { formatDateTime } from '../../lib/format'
import type { Company, User } from '../../lib/types'
import ClientsBlock from './ClientsBlock'
import { RequisiteFields, TaxFields } from './CompanyFields'
import type { PatentData } from './PatentForm'
import PatentList from './PatentList'
import { useStaff } from './useStaff'

export default function CompanyCard({ user }: { user: User }) {
  const id = Number(useParams().id)
  const company = useQuery({
    queryKey: ['company', id],
    queryFn: () => api<Company>(`/companies/${id}`),
    refetchOnMount: 'always',
  })

  return (
    <div className="space-y-4">
      <Link to="/companies" className="text-sm text-blue-600 underline">
        ← Все компании
      </Link>
      <ErrorText error={company.error} />
      {company.data && <Loaded key={id} company={company.data} user={user} />}
    </div>
  )
}

function useCompanyAction<T>(id: number, action: (input: T) => Promise<unknown>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: action,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['company', id] })
      void queryClient.invalidateQueries({ queryKey: ['companies'] })
    },
  })
}

function Loaded({ company, user }: { company: Company; user: User }) {
  const base = `/companies/${company.id}`
  const refresh = useCompanyAction(company.id, () =>
    api(`${base}/refresh-dadata`, { method: 'POST' }),
  )
  const archive = useCompanyAction(company.id, (is_archived: boolean) =>
    api(base, { method: 'PATCH', body: { is_archived } }),
  )

  return (
    <>
      <h1 className="text-xl font-semibold">{company.short_name || company.name}</h1>
      {company.is_archived && <Alert kind="warning">Компания в архиве.</Alert>}
      {/* key пересоздаёт форму, когда сохранённые поля изменились */}
      <EditForm key={JSON.stringify(toForm(company))} company={company} />
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Button variant="secondary" disabled={refresh.isPending} onClick={() => refresh.mutate(null)}>
          Обновить из DaData
        </Button>
        {company.dadata_updated_at && (
          <span className="text-slate-500 dark:text-slate-400">
            обновлено {formatDateTime(company.dadata_updated_at)}
          </span>
        )}
      </div>
      <ErrorText error={refresh.error} />
      {company.entity_type === 'ip' && <Patents company={company} />}
      <ClientsBlock company={company} />
      {user.role === 'admin' && (
        <Reassign key={company.accountant_id} company={company} />
      )}
      <ErrorText error={archive.error} />
      <Button
        variant={company.is_archived ? 'secondary' : 'danger'}
        disabled={archive.isPending}
        onClick={() => {
          if (company.is_archived || window.confirm('Перенести компанию в архив?')) {
            archive.mutate(!company.is_archived)
          }
        }}
      >
        {company.is_archived ? 'Вернуть из архива' : 'В архив'}
      </Button>
    </>
  )
}

function EditForm({ company }: { company: Company }) {
  const [form, setForm] = useState(() => toForm(company))
  const save = useCompanyAction(company.id, () =>
    api(`/companies/${company.id}`, { method: 'PATCH', body: { company: form } }),
  )
  const dirty = JSON.stringify(form) !== JSON.stringify(toForm(company))

  return (
    <>
      <Card title="Реквизиты">
        <RequisiteFields form={form} onChange={setForm} />
      </Card>
      <Card title="Налоги">
        <TaxFields form={form} onChange={setForm} />
      </Card>
      <ErrorText error={save.error} />
      <Button disabled={!dirty || save.isPending} onClick={() => save.mutate(null)}>
        Сохранить изменения
      </Button>
    </>
  )
}

function Patents({ company }: { company: Company }) {
  const base = `/companies/${company.id}/patents`
  const change = useCompanyAction(
    company.id,
    ({ method, id, body }: { method: 'POST' | 'PATCH' | 'DELETE'; id?: number; body?: PatentData }) =>
      api(id ? `${base}/${id}` : base, { method, body }),
  )
  // сервер не принимает id в теле запроса
  const fields = ({ number, region, date_start, date_end, cost_kopecks }: PatentData) => ({
    number,
    region,
    date_start,
    date_end,
    cost_kopecks,
  })

  return (
    <Card title="Патенты">
      <ErrorText error={change.error} />
      <PatentList
        patents={company.patents}
        onAdd={(patent) => change.mutate({ method: 'POST', body: fields(patent) })}
        onEdit={(index, patent) =>
          change.mutate({ method: 'PATCH', id: company.patents[index].id, body: fields(patent) })
        }
        onRemove={(index) => change.mutate({ method: 'DELETE', id: company.patents[index].id })}
      />
    </Card>
  )
}

function Reassign({ company }: { company: Company }) {
  const staff = useStaff(true)
  const [accountantId, setAccountantId] = useState(company.accountant_id ?? 0)
  const reassign = useCompanyAction(company.id, () =>
    api(`/admin/companies/${company.id}/reassign`, {
      method: 'POST',
      body: { accountant_id: accountantId },
    }),
  )

  return (
    <Card title="Ответственный">
      <Select
        label="Бухгалтер"
        value={accountantId}
        onChange={(event) => setAccountantId(Number(event.target.value))}
      >
        {!staff.data?.some((member) => member.id === company.accountant_id) && (
          <option value={company.accountant_id ?? 0}>
            {company.accountant_name ? `${company.accountant_name} (отключён)` : 'Не назначен'}
          </option>
        )}
        {staff.data?.map((member) => (
          <option key={member.id} value={member.id}>
            {member.name}
          </option>
        ))}
      </Select>
      <p className="text-sm text-slate-500 dark:text-slate-400">
        При передаче неиспользованные приглашения клиентов отзываются.
      </p>
      <ErrorText error={reassign.error} />
      <Button
        disabled={accountantId === (company.accountant_id ?? 0) || reassign.isPending}
        onClick={() => reassign.mutate(null)}
      >
        Передать компанию
      </Button>
    </Card>
  )
}
