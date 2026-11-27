import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router'

import FileDrop from '../../components/FileDrop'
import { Alert, Button, ErrorText, Select, Tabs } from '../../components/ui'
import { api } from '../../lib/api'
import { formatDate, formatKopecks, toRublesText } from '../../lib/company'
import {
  type Demand,
  type DemandStep,
  EMPTY_DEMAND,
  nextDue,
  type Recognized,
  useDemands,
} from '../../lib/demands'
import { canEdit } from '../../lib/roles'
import { relativeDay, todayIso } from '../../lib/tasks'
import type { User } from '../../lib/types'
import { useRefreshTasks } from '../../lib/useTasks'
import DemandForm, { type DemandBody } from './DemandForm'

interface Draft {
  file: File | null
  found: Recognized | null
}

function NewDemand({ draft, onClose }: { draft: Draft; onClose: () => void }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const refresh = useRefreshTasks()
  const found = draft.found
  const initial = {
    ...EMPTY_DEMAND,
    company_id: found?.company_id ?? 0,
    knd: found?.knd ?? '',
    number: found?.number ?? '',
    doc_date: found?.doc_date ?? '',
    response_workdays: found?.response_workdays ? String(found.response_workdays) : '',
    response_date: found?.response_date ?? '',
    amount: toRublesText(found?.amount_kopecks ?? null),
    note: found?.note ?? '',
  }

  const create = async (body: DemandBody) => {
    const created = await api<Demand>('/demands', { method: 'POST', body })
    let failed = false
    if (draft.file) {
      try {
        await api(`/demands/${created.id}/file`, { method: 'POST', file: draft.file })
      } catch {
        // требование уже заведено: файл можно приложить на его странице
        failed = true
      }
    }
    refresh()
    void queryClient.invalidateQueries({ queryKey: ['demands'] })
    await navigate(`/demands/${created.id}${failed ? '?file=failed' : ''}`)
  }

  return (
    <div className="space-y-3">
      {found && !found.readable && (
        <Alert kind="warning">
          Текст в файле не распознан (скан или фото). Заполните поля по документу, файл
          сохранится вместе с требованием.
        </Alert>
      )}
      {found?.readable && !found.company_id && (
        <Alert kind="warning">
          {found.inn
            ? `Организации с ИНН ${found.inn} нет среди ваших.`
            : 'ИНН в файле не найден.'}{' '}
          Выберите организацию сами.
        </Alert>
      )}
      {found?.readable && (
        <Alert>Проверьте распознанные данные по документу и сохраните.</Alert>
      )}
      <DemandForm
        initial={initial}
        isNew
        submitLabel="Сохранить требование"
        onSubmit={create}
        onCancel={onClose}
      />
    </div>
  )
}

function Step({ title, step, today }: { title: string; step: DemandStep | null; today: string }) {
  if (!step) return null
  const open = step.status === 'planned'
  const overdue = open && step.due_date < today
  return (
    <span className="flex flex-wrap items-baseline gap-x-2 text-sm">
      <span aria-hidden="true" className={open ? 'text-slate-400' : 'font-bold text-green-600'}>
        {open ? '○' : '✓'}
      </span>
      <span>
        {title}: {formatDate(step.due_date)}
      </span>
      {open && (
        <span
          className={
            overdue
              ? 'font-semibold text-red-700 dark:text-red-400'
              : 'text-slate-500 dark:text-slate-400'
          }
        >
          {relativeDay(step.due_date, today)}
        </span>
      )}
    </span>
  )
}

/** Требования инспекции: загрузка и список по ближайшему сроку. */
export default function DemandsPage({ user }: { user: User }) {
  const today = todayIso()
  const editable = canEdit(user.role)
  const demands = useDemands()
  const [tab, setTab] = useState<'open' | 'closed'>('open')
  const [company, setCompany] = useState('')
  const [draft, setDraft] = useState<Draft | null>(null)
  const recognize = useMutation({
    mutationFn: async (file: File) => ({
      file,
      found: await api<Recognized>('/demands/recognize', { method: 'POST', file }),
    }),
    onSuccess: setDraft,
  })

  const all = demands.data ?? []
  const companies = [...new Map(all.map((item) => [item.company_id, item.company_name]))]
  const mine = all.filter((item) => !company || item.company_id === Number(company))
  const count = (closed: boolean) => mine.filter((item) => item.closed === closed).length
  const shown = mine
    .filter((item) => item.closed === (tab === 'closed'))
    .sort((a, b) => nextDue(a).localeCompare(nextDue(b)) * (tab === 'closed' ? -1 : 1))

  if (draft) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-bold">Требования</h1>
        {draft.file && <p className="text-sm break-all">{draft.file.name}</p>}
        <NewDemand draft={draft} onClose={() => setDraft(null)} />
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Требования</h1>
      {editable && (
        <>
          <FileDrop
            title="Загрузить требование"
            hint="PDF из учётной программы или оператора — реквизиты и сроки распознаются. Можно фото."
            accept=".pdf,image/*"
            disabled={recognize.isPending}
            onFiles={([file]) => recognize.mutate(file)}
          />
          {recognize.isPending && <p className="text-sm">Читаем файл…</p>}
          <ErrorText error={recognize.error} />
          <Button variant="secondary" onClick={() => setDraft({ file: null, found: null })}>
            Добавить без файла
          </Button>
        </>
      )}
      <Tabs
        tabs={[
          ['open', `Открытые · ${count(false)}`],
          ['closed', `Выполненные · ${count(true)}`],
        ]}
        active={tab}
        onChange={setTab}
      />
      {companies.length > 1 && (
        <Select
          label="Организация"
          value={company}
          onChange={(event) => setCompany(event.target.value)}
        >
          <option value="">Все организации</option>
          {companies.map(([id, name]) => (
            <option key={id} value={id}>
              {name}
            </option>
          ))}
        </Select>
      )}
      <ErrorText error={demands.error} />
      {demands.data && shown.length === 0 && (
        <p className="py-6 text-center text-slate-500 dark:text-slate-400">Требований нет.</p>
      )}
      <ul className="grid gap-3 lg:grid-cols-2">
        {shown.map((item) => (
          <li key={item.id}>
            <Link
              to={`/demands/${item.id}`}
              className="block h-full space-y-1 rounded-xl border border-slate-200 bg-white p-4 hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-900 dark:hover:bg-slate-800/50"
            >
              <span className="block font-semibold break-words">{item.company_name}</span>
              <span className="block text-sm break-words">
                {item.name}
                {item.number && ` № ${item.number}`} от {formatDate(item.doc_date)}
              </span>
              {item.amount_kopecks != null && (
                <span className="block text-sm font-medium tabular-nums">
                  {formatKopecks(item.amount_kopecks)}
                </span>
              )}
              <Step title="Квитанция" step={item.receipt} today={today} />
              <Step title={item.response_label} step={item.response} today={today} />
            </Link>
          </li>
        ))}
      </ul>
    </div>
  )
}
