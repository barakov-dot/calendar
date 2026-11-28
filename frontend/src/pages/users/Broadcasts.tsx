import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router'

import { Alert, Button, Card, Checkbox, ErrorText } from '../../components/ui'
import { api } from '../../lib/api'
import { formatDateTime } from '../../lib/format'
import type { Role } from '../../lib/types'
import CompanyAudience, { type CompanyGroup } from './CompanyAudience'

const MAX_LENGTH = 3500

const GROUPS: [Role, string][] = [
  ['chief', 'Главным бухгалтерам'],
  ['accountant', 'Бухгалтерам'],
  ['assistant', 'Помощникам'],
  ['client', 'Клиентам'],
]

export interface Preview {
  recipients: string[]
  unreachable: { id: number; name: string; reason: string }[]
}

export interface Broadcast {
  id: number
  text: string
  roles: Role[]
  company_names: string[]
  company_groups: CompanyGroup[]
  archived: boolean
  author_name: string
  created_at: string
  total: number
  sent: number
  pending: number
  failed: number
  skipped: number
}

const DELIVERY: Record<string, string> = {
  pending: 'ждёт отправки',
  sent: 'доставлено',
  failed: 'не доставлено',
  skipped: 'пропущено',
}

const MEMBERS: Record<CompanyGroup, string> = {
  client: 'клиенты',
  accountant: 'бухгалтеры',
  assistant: 'помощники',
}

function audienceName(item: Broadcast): string {
  const parts = GROUPS.filter(([role]) => item.roles.includes(role)).map(([, title]) =>
    title.toLowerCase(),
  )
  if (item.company_names?.length) {
    const who = item.company_groups.map((group) => MEMBERS[group]).join(', ')
    parts.push(`${item.company_names.join(', ')} (${who})`)
  }
  return parts.join('; ') || 'выбранным пользователям'
}

function Deliveries({ id }: { id: number }) {
  const list = useQuery({
    queryKey: ['deliveries', id],
    queryFn: () =>
      api<{ id: number; name: string; status: string }[]>(`/admin/broadcasts/${id}/deliveries`),
    refetchOnMount: 'always',
  })
  return (
    <>
      <ErrorText error={list.error} />
      <ul className="text-sm">
        {list.data?.map((item) => (
          <li key={item.id}>
            <Link to={`/users/${item.id}`} className="underline">
              {item.name}
            </Link>{' '}
            — {DELIVERY[item.status] ?? item.status}
          </li>
        ))}
      </ul>
    </>
  )
}

function History() {
  const [opened, setOpened] = useState<number | null>(null)
  const [archive, setArchive] = useState(false)
  const queryClient = useQueryClient()
  const list = useQuery({
    queryKey: ['broadcasts', archive],
    queryFn: () => api<Broadcast[]>(`/admin/broadcasts${archive ? '?archived=true' : ''}`),
    refetchOnMount: 'always',
    // пока что-то в очереди, счётчики обновляются сами
    refetchInterval: (query) => (query.state.data?.some((item) => item.pending) ? 3000 : false),
  })
  const reload = () => queryClient.invalidateQueries({ queryKey: ['broadcasts'] })
  const move = useMutation({
    mutationFn: (ids: number[]) =>
      api('/admin/broadcasts/archive', { method: 'POST', body: { ids, archived: !archive } }),
    onSuccess: reload,
  })
  const remove = useMutation({
    mutationFn: (id: number) => api(`/admin/broadcasts/${id}`, { method: 'DELETE' }),
    onSuccess: reload,
  })
  const busy = move.isPending || remove.isPending

  return (
    <Card title={archive ? 'Архив рассылок' : 'Отправленные'}>
      <Checkbox label="Показать архив" checked={archive} onChange={setArchive} />
      <ErrorText error={list.error ?? move.error ?? remove.error} />
      {list.data?.length === 0 && (
        <p className="text-sm">{archive ? 'В архиве пусто.' : 'Здесь пусто.'}</p>
      )}
      {!archive && (list.data?.length ?? 0) > 1 && (
        <Button
          variant="secondary"
          disabled={busy}
          onClick={() => move.mutate(list.data!.map((item) => item.id))}
        >
          Убрать все в архив
        </Button>
      )}
      <ul className="divide-y divide-slate-200 dark:divide-slate-700">
        {list.data?.map((item) => (
          <li key={item.id} className="space-y-1 py-3">
            <p className="text-sm break-words whitespace-pre-wrap">{item.text}</p>
            <p className="text-sm break-words text-slate-500 dark:text-slate-400">
              {formatDateTime(item.created_at)} · {audienceName(item)}
            </p>
            <p className="text-sm">
              Доставлено {item.sent} из {item.total}
              {item.pending > 0 && `, в очереди ${item.pending}`}
              {item.failed > 0 && `, не доставлено ${item.failed}`}
              {item.skipped > 0 && `, пропущено ${item.skipped}`}
            </p>
            <button
              type="button"
              aria-expanded={opened === item.id}
              onClick={() => setOpened(opened === item.id ? null : item.id)}
              className="cursor-pointer text-sm text-blue-700 underline dark:text-blue-300"
            >
              {opened === item.id ? 'Скрыть получателей' : 'Кому'}
            </button>
            {opened === item.id && <Deliveries id={item.id} />}
            <div className="flex flex-wrap gap-2 pt-1">
              <Button variant="secondary" disabled={busy} onClick={() => move.mutate([item.id])}>
                {archive ? 'Вернуть из архива' : 'В архив'}
              </Button>
              <Button
                variant="danger"
                disabled={busy}
                onClick={() => {
                  const waiting = item.pending
                    ? ` Ещё не отправленные (${item.pending}) не уйдут.`
                    : ''
                  const text = `Удалить рассылку из истории?${waiting} Доставленные сообщения останутся у получателей в Telegram.`
                  if (window.confirm(text)) remove.mutate(item.id)
                }}
              >
                Удалить
              </Button>
            </div>
          </li>
        ))}
      </ul>
    </Card>
  )
}

/** Сообщение от бота выбранным пользователям. Только администратору. */
export default function Broadcasts() {
  const [params, setParams] = useSearchParams()
  const userIds = (params.get('users') ?? '').split(',').map(Number).filter(Number.isInteger)
  const chosen = userIds.filter((id) => id > 0)
  const [roles, setRoles] = useState<Role[]>([])
  const [text, setText] = useState('')
  const [companyIds, setCompanyIds] = useState<number[]>([])
  const [companyGroups, setCompanyGroups] = useState<CompanyGroup[]>(['client'])
  const queryClient = useQueryClient()
  const byCompany = companyIds.length > 0 && companyGroups.length > 0
  const audience = {
    roles,
    user_ids: chosen,
    company_ids: byCompany ? companyIds : [],
    company_groups: byCompany ? companyGroups : [],
  }
  const targeted = roles.length > 0 || chosen.length > 0 || byCompany
  const preview = useQuery({
    queryKey: ['broadcast-preview', JSON.stringify(audience)],
    queryFn: () =>
      api<Preview>('/admin/broadcasts/preview', { method: 'POST', body: audience }),
    enabled: targeted,
    placeholderData: keepPreviousData,
    refetchOnMount: 'always',
  })
  const found = targeted && !preview.isPlaceholderData ? preview.data : undefined
  const count = found?.recipients.length ?? 0
  const send = useMutation({
    mutationFn: () =>
      api<Broadcast>('/admin/broadcasts', { method: 'POST', body: { ...audience, text } }),
    onSuccess: () => {
      setText('')
      setRoles([])
      setCompanyIds([])
      setCompanyGroups(['client'])
      setParams({}, { replace: true })
      void queryClient.invalidateQueries({ queryKey: ['broadcasts'] })
    },
  })

  return (
    <div className="grid items-start gap-4 lg:grid-cols-2">
      <Card title="Рассылка">
        <fieldset className="space-y-2">
          <legend className="mb-1 text-sm font-medium">Кому</legend>
          {GROUPS.map(([role, title]) => (
            <Checkbox
              key={role}
              label={title}
              checked={roles.includes(role)}
              onChange={(on) =>
                setRoles(on ? [...roles, role] : roles.filter((item) => item !== role))
              }
            />
          ))}
        </fieldset>
        <CompanyAudience
          ids={companyIds}
          groups={companyGroups}
          onChange={(ids, groups) => {
            setCompanyIds(ids)
            setCompanyGroups(groups)
          }}
        />
        {chosen.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span>Отмечены по одному: {chosen.length}</span>
            <Button variant="secondary" onClick={() => setParams({}, { replace: true })}>
              Убрать
            </Button>
          </div>
        )}
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Отдельных людей отметьте в разделе{' '}
          <Link to="/users" className="underline">
            «Пользователи»
          </Link>
          .
        </p>
        <ErrorText error={preview.error} />
        {found && (
          <div className="space-y-2 text-sm">
            <details>
              <summary className="cursor-pointer font-medium">Получателей: {count}</summary>
              <p>{found.recipients.join(', ')}</p>
            </details>
            {found.unreachable.length > 0 && (
              <Alert kind="warning">
                Не получат:{' '}
                {found.unreachable.map((item) => `${item.name} — ${item.reason}`).join('; ')}
              </Alert>
            )}
          </div>
        )}
        <label className="block text-sm">
          <span className="mb-1 block font-medium">Сообщение</span>
          <textarea
            rows={7}
            maxLength={MAX_LENGTH}
            value={text}
            onChange={(event) => setText(event.target.value)}
            className="w-full rounded-lg border border-slate-300 bg-transparent px-3 py-2 dark:border-slate-600"
          />
          <span className="text-slate-500 dark:text-slate-400">
            {text.length} из {MAX_LENGTH}. Все получат один и тот же текст: о делах
            конкретной организации пишите, только если выбрана она одна.
          </span>
        </label>
        <ErrorText error={send.error} />
        {send.isSuccess && <Alert kind="success">Рассылка поставлена в очередь.</Alert>}
        <Button
          disabled={!text.trim() || count === 0 || send.isPending}
          onClick={() => {
            if (window.confirm(`Отправить сообщение? Получателей: ${count}.`)) send.mutate()
          }}
        >
          Отправить
        </Button>
      </Card>
      <History />
    </div>
  )
}
