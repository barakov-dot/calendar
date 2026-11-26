import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router'

import { Alert, Button, Card, ErrorText, Field, Select } from '../../components/ui'
import { api } from '../../lib/api'
import { type CompanyForm, EMPTY_COMPANY, toForm, withRegime } from '../../lib/company'
import type { Company, Party, User } from '../../lib/types'
import { RequisiteFields, TaxFields } from './CompanyFields'
import type { PatentData } from './PatentForm'
import PatentList from './PatentList'
import { useStaff } from './useStaff'

const STATUS_WARNINGS: Record<string, string> = {
  LIQUIDATING: 'Организация в процессе ликвидации.',
  LIQUIDATED: 'Организация ликвидирована.',
  BANKRUPT: 'Организация банкротится.',
  REORGANIZING: 'Организация в процессе реорганизации.',
}

const SEARCH_DELAY_MS = 400

export default function NewCompany({ user }: { user: User }) {
  const [draft, setDraft] = useState<{ form: CompanyForm; warning?: string } | null>(null)
  return draft ? (
    <Details user={user} initial={draft.form} warning={draft.warning} onBack={() => setDraft(null)} />
  ) : (
    <Search
      onManual={() => setDraft({ form: EMPTY_COMPANY })}
      onSelect={(party) =>
        setDraft({
          form: withRegime(toForm(party), 'usn6'),
          warning: STATUS_WARNINGS[party.status],
        })
      }
    />
  )
}

function Search({
  onSelect,
  onManual,
}: {
  onSelect: (party: Party) => void
  onManual: () => void
}) {
  const [text, setText] = useState('')
  const [query, setQuery] = useState('')
  // запрос уходит после паузы в наборе, чтобы не тратить лимит DaData
  useEffect(() => {
    const timer = setTimeout(() => setQuery(text.trim()), SEARCH_DELAY_MS)
    return () => clearTimeout(timer)
  }, [text])
  const found = useQuery({
    queryKey: ['suggest', query],
    queryFn: () =>
      api<{ enabled: boolean; suggestions: Party[] }>(
        `/companies/suggest?${new URLSearchParams({ q: query })}`,
      ),
    enabled: query.length >= 3,
  })

  return (
    <Card title="Добавить компанию">
      <Field
        label="ИНН или название"
        autoFocus
        value={text}
        onChange={(event) => setText(event.target.value)}
      />
      <ErrorText error={found.error} />
      {found.isFetching && <p className="text-sm">Ищем…</p>}
      {found.data?.enabled === false && (
        <Alert kind="warning">DaData выключена или не настроена. Заполните карточку вручную.</Alert>
      )}
      {found.data?.enabled && found.data.suggestions.length === 0 && (
        <p className="text-sm">Ничего не найдено.</p>
      )}
      <ul className="space-y-2">
        {found.data?.suggestions.map((party) => (
          <li key={`${party.inn}-${party.kpp}`}>
            <button
              type="button"
              onClick={() => onSelect(party)}
              className="w-full rounded-lg border border-slate-200 p-3 text-left hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800"
            >
              <span className="block font-medium">{party.short_name || party.name}</span>
              <span className="block text-sm text-slate-500 dark:text-slate-400">
                ИНН {party.inn} · {party.address}
              </span>
              {STATUS_WARNINGS[party.status] && (
                <span className="block text-sm text-red-600">{STATUS_WARNINGS[party.status]}</span>
              )}
            </button>
          </li>
        ))}
      </ul>
      <Button variant="secondary" onClick={onManual}>
        Заполнить вручную
      </Button>
    </Card>
  )
}

function Details({
  user,
  initial,
  warning,
  onBack,
}: {
  user: User
  initial: CompanyForm
  warning?: string
  onBack: () => void
}) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [form, setForm] = useState(initial)
  const [patents, setPatents] = useState<PatentData[]>([])
  const [accountantId, setAccountantId] = useState(user.id)
  const staff = useStaff(user.role === 'admin')
  const create = useMutation({
    mutationFn: () =>
      api<Company>('/companies', {
        method: 'POST',
        body: {
          company: form,
          accountant_id: accountantId,
          patents: form.entity_type === 'ip' ? patents : [],
        },
      }),
    onSuccess: (company) => {
      void queryClient.invalidateQueries({ queryKey: ['companies'] })
      navigate(`/companies/${company.id}`, { replace: true })
    },
  })

  return (
    <div className="space-y-4">
      <Button variant="secondary" onClick={onBack}>
        ← К поиску
      </Button>
      {warning && <Alert kind="warning">{warning}</Alert>}
      <div className="grid items-start gap-4 lg:grid-cols-2">
        <Card title="Реквизиты">
          <RequisiteFields form={form} onChange={setForm} />
        </Card>
        <Card title="Налоги и выплаты">
          <TaxFields form={form} onChange={setForm} />
        </Card>
      </div>
      {form.entity_type === 'ip' && (
        <Card title="Патенты">
          <PatentList
            patents={patents}
            onAdd={(patent) => setPatents([...patents, patent])}
            onEdit={(index, patent) =>
              setPatents(patents.map((old, i) => (i === index ? patent : old)))
            }
            onRemove={(index) => setPatents(patents.filter((_, i) => i !== index))}
          />
        </Card>
      )}
      {user.role === 'admin' && (
        <Card title="Ответственный">
          <Select
            label="Бухгалтер"
            value={accountantId}
            onChange={(event) => setAccountantId(Number(event.target.value))}
          >
            {staff.data?.map((member) => (
              <option key={member.id} value={member.id}>
                {member.name}
              </option>
            ))}
          </Select>
        </Card>
      )}
      <ErrorText error={create.error} />
      <Button disabled={create.isPending} onClick={() => create.mutate()}>
        Создать компанию
      </Button>
    </div>
  )
}
