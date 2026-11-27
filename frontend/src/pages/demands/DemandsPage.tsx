import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router'

import FileDrop from '../../components/FileDrop'
import { Alert, Button, ErrorText, Select, Tabs } from '../../components/ui'
import { api } from '../../lib/api'
import { toRublesText } from '../../lib/company'
import {
  type Demand,
  EMPTY_DEMAND,
  nextDue,
  type Recognized,
  useDemands,
} from '../../lib/demands'
import { canEdit } from '../../lib/roles'
import type { User } from '../../lib/types'
import { useRefreshTasks } from '../../lib/useTasks'
import DemandCards from './DemandCards'
import DemandForm, { type DemandBody } from './DemandForm'

interface Draft {
  file: File | null
  found: Recognized | null
  companyId: number
}

function NewDemand({ draft, onClose }: { draft: Draft; onClose: () => void }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const refresh = useRefreshTasks()
  const found = draft.found
  const initial = {
    ...EMPTY_DEMAND,
    company_id: found?.company_id ?? draft.companyId,
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

/** Требования инспекции: загрузка и список по ближайшему сроку. */
export default function DemandsPage({ user }: { user: User }) {
  const editable = canEdit(user.role)
  const demands = useDemands()
  const [tab, setTab] = useState<'open' | 'closed'>('open')
  const [params] = useSearchParams()
  const [company, setCompany] = useState(params.get('company') ?? '')
  const [draft, setDraft] = useState<Draft | null>(null)
  const recognize = useMutation({
    mutationFn: async (file: File) => ({
      file,
      companyId: Number(params.get('company') ?? 0),
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
          <Button variant="secondary" onClick={() =>
              setDraft({ file: null, found: null, companyId: Number(company) })
            }>
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
      <DemandCards demands={shown} />
    </div>
  )
}
