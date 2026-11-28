import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'

import { Alert, Button, Card, ErrorText, Tabs } from '../../components/ui'
import { api } from '../../lib/api'
import { ENTITY_NAMES, REGIME_NAMES, toForm } from '../../lib/company'
import { formatDateTime } from '../../lib/format'
import { canEdit, isManager } from '../../lib/roles'
import type { Company, User } from '../../lib/types'
import { ReminderBlock } from '../reminders/Reminders'
import CompanyDemands from './CompanyDemands'
import CompanyTasks from './CompanyTasks'
import ClientsBlock from './ClientsBlock'
import { RequisiteFields, TaxFields } from './CompanyFields'
import type { PatentData } from './PatentForm'
import PatentList from './PatentList'
import RosstatBlock from './RosstatBlock'
import SignaturesBlock from './SignaturesBlock'
import { StaffPicker, type StaffChoice } from './StaffPicker'

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
        ← Все организации
      </Link>
      <ErrorText error={company.error} />
      {company.data && <Loaded key={id} company={company.data} user={user} />}
    </div>
  )
}

const TAB_KEYS = [
  'tasks',
  'demands',
  'rosstat',
  'params',
  'clients',
  'reminders',
  'signatures',
] as const
type Tab = (typeof TAB_KEYS)[number]

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
  const editable = canEdit(user.role)
  const base = `/companies/${company.id}`
  const refresh = useCompanyAction(company.id, () =>
    api(`${base}/refresh-dadata`, { method: 'POST' }),
  )
  const archive = useCompanyAction(company.id, (is_archived: boolean) =>
    api(base, { method: 'PATCH', body: { is_archived } }),
  )

  // вкладку можно указать в адресе: так открывают подписи из раздела «ЭЦП»
  const [params] = useSearchParams()
  const [tab, setTab] = useState<Tab>(
    () => TAB_KEYS.find((key) => key === params.get('tab')) ?? 'tasks',
  )
  const active = editable && !company.is_archived
  const tabs: [Tab, string][] = [
    ['tasks', 'Задачи'],
    ['demands', 'Требования'],
    ['rosstat', 'Росстат'],
    ['params', 'Реквизиты и налоги'],
    ['clients', `Клиенты · ${company.members.length}`],
    ['reminders', 'Напоминания'],
    ['signatures', 'ЭЦП'],
  ]

  return (
    <>
      <div className="flex flex-wrap items-baseline gap-x-3">
        <h1 className="text-xl font-semibold">{company.short_name || company.name}</h1>
        <span className="text-sm text-slate-500 dark:text-slate-400">
          ИНН {company.inn} · {ENTITY_NAMES[company.entity_type]} ·{' '}
          {REGIME_NAMES[company.main_regime]}
        </span>
      </div>
      {company.is_archived && <Alert kind="warning">Компания в архиве.</Alert>}
      <Tabs tabs={tabs} active={tab} onChange={setTab} />
      {tab === 'tasks' && <CompanyTasks companyId={company.id} editable={active} />}
      {tab === 'demands' && <CompanyDemands companyId={company.id} editable={active} />}
      {tab === 'rosstat' && <RosstatBlock companyId={company.id} editable={active} />}
      {tab === 'reminders' && <ReminderBlock companyId={company.id} editable={active} />}
      {tab === 'clients' && <ClientsBlock company={company} user={user} />}
      {tab === 'signatures' && <SignaturesBlock companyId={company.id} editable={active} />}
      {/* вкладка скрывается, а не удаляется: несохранённые правки не теряются */}
      <div className={tab === 'params' ? 'space-y-4' : 'hidden'}>
        <div className={`flex flex-wrap items-center gap-2 text-sm ${editable ? '' : 'hidden'}`}>
          <Button
            variant="secondary"
            disabled={refresh.isPending}
            onClick={() => refresh.mutate(null)}
          >
            Обновить из DaData
          </Button>
          {company.dadata_updated_at && (
            <span className="text-slate-500 dark:text-slate-400">
              обновлено {formatDateTime(company.dadata_updated_at)}
            </span>
          )}
        </div>
        <ErrorText error={refresh.error} />
        {/* помощник видит реквизиты и параметры, но не меняет их */}
        <fieldset disabled={!editable} className="min-w-0 space-y-4">
          {/* key пересоздаёт форму, когда сохранённые поля изменились */}
          <EditForm key={JSON.stringify(toForm(company))} company={company} editable={editable} />
        </fieldset>
        {company.entity_type === 'ip' && (
          <fieldset disabled={!editable} className="min-w-0">
            <Patents company={company} />
          </fieldset>
        )}
        {isManager(user.role) ? (
          <Staff key={JSON.stringify(toChoice(company))} company={company} />
        ) : (
          <Card title="Сотрудники">
            <p className="text-sm">Бухгалтеры: {company.accountant_name || 'не назначены'}</p>
            {company.assistants.length > 0 && (
              <p className="text-sm">
                Помощники: {company.assistants.map((member) => member.name).join(', ')}
              </p>
            )}
          </Card>
        )}
        <ErrorText error={archive.error} />
        {editable && (
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
        )}
      </div>
    </>
  )
}

function EditForm({ company, editable }: { company: Company; editable: boolean }) {
  const [form, setForm] = useState(() => toForm(company))
  const save = useCompanyAction(company.id, () =>
    api(`/companies/${company.id}`, { method: 'PATCH', body: { company: form } }),
  )
  const dirty = JSON.stringify(form) !== JSON.stringify(toForm(company))

  return (
    <>
      <div className="grid items-start gap-4 lg:grid-cols-2">
        <Card title="Реквизиты">
          <RequisiteFields form={form} onChange={setForm} />
        </Card>
        <Card title="Налоги и выплаты">
          <TaxFields form={form} onChange={setForm} />
        </Card>
      </div>
      <ErrorText error={save.error} />
      {editable && (
        <Button disabled={!dirty || save.isPending} onClick={() => save.mutate(null)}>
          Сохранить изменения
        </Button>
      )}
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

function toChoice(company: Company): StaffChoice {
  return {
    accountant_ids: company.accountants.map((member) => member.id),
    assistant_ids: company.assistants.map((member) => member.id),
  }
}

function Staff({ company }: { company: Company }) {
  const [choice, setChoice] = useState(() => toChoice(company))
  const save = useCompanyAction(company.id, () =>
    api(`/admin/companies/${company.id}/staff`, { method: 'POST', body: choice }),
  )
  const same = (left: number[], right: number[]) =>
    left.length === right.length && left.every((id) => right.includes(id))
  const saved = toChoice(company)
  const dirty =
    !same(choice.accountant_ids, saved.accountant_ids) ||
    !same(choice.assistant_ids, saved.assistant_ids)

  return (
    <Card title="Сотрудники">
      <StaffPicker value={choice} onChange={setChoice} current={company} />
      <p className="text-sm text-slate-500 dark:text-slate-400">
        Все отмеченные бухгалтеры получают напоминания и сообщения клиентов. Неиспользованные
        приглашения клиентов, выданные снятыми сотрудниками, отзываются.
      </p>
      <ErrorText error={save.error} />
      <Button
        disabled={!dirty || choice.accountant_ids.length === 0 || save.isPending}
        onClick={() => save.mutate(null)}
      >
        Сохранить сотрудников
      </Button>
    </Card>
  )
}
