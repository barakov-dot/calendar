import { useState } from 'react'
import { useSearchParams } from 'react-router'

import AddButton from '../../components/AddButton'
import { SubstitutionNotice } from '../../components/Substitutions'
import TaskFeed from '../../components/TaskFeed'
import { Alert, Button, ErrorText, Select } from '../../components/ui'
import { canEdit } from '../../lib/roles'
import {
  addDays,
  isOverdue,
  KIND_NAMES,
  plural,
  STATUS_NAMES,
  type Task,
  tasksWord,
  todayIso,
} from '../../lib/tasks'
import type { User } from '../../lib/types'
import { useCompanies } from '../../lib/useCompanies'
import { useTasks } from '../../lib/useTasks'

const TABS = [
  ['today', 'Сегодня', 0],
  ['week', 'Неделя', 7],
  ['month', 'Месяц', 30],
  ['all', 'Всё', null],
] as const
type Tab = (typeof TABS)[number][0]

function headline(tab: Tab, count: number, status: string): string {
  if (status !== 'planned' || tab === 'all') return tab === 'all' ? 'Все задачи' : 'Задачи'
  const when = { today: 'Сегодня', week: 'На неделе', month: 'За 30 дней' }[tab]
  return count ? `${when} ${count} ${tasksWord(count)}` : `${when} задач нет`
}

const CONTROL =
  'rounded-xl border border-slate-200 bg-white px-2 py-2.5 sm:px-3 text-sm dark:border-slate-700 dark:bg-slate-900'

/** Главный экран сотрудника. Выбранное хранится в адресе и не теряется при возврате. */
export default function Tasks({ user }: { user: User }) {
  const today = todayIso()
  const [params, setParams] = useSearchParams()
  const set = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(params)
    for (const [key, value] of Object.entries(changes)) {
      if (value === null) next.delete(key)
      else next.set(key, value)
    }
    setParams(next, { replace: true })
  }

  const tab = TABS.find(([key]) => key === params.get('tab'))?.[0] ?? 'week'
  const company_id = params.get('company') ?? ''
  const kind = params.get('kind') ?? ''
  const status = params.get('status') ?? 'planned'
  const [filtersOpen, setFiltersOpen] = useState(false)
  const filtered = kind !== '' || params.get('status') !== null
  // прошедшие сроки открываются по нажатию, иначе они заслоняют ближайшие дела
  const showLate = params.get('late') === '1'
  const showSubmitted = params.get('submitted') === '1'

  const companies = useCompanies()
  const base = { company_id, kind }
  const statusParam = status === 'all' ? '' : status
  const withOverdue = status === 'planned' || status === 'all'
  const overdue = useTasks(
    { ...base, status: 'planned', to: addDays(today, -1), hide_history: true },
    withOverdue,
  )
  const soon = useTasks({ ...base, status: statusParam, from: today, to: addDays(today, 30) })
  const everything = useTasks(
    { ...base, status: statusParam, from: status === 'planned' ? today : undefined },
    tab === 'all',
  )
  const submitted = useTasks({
    company_id,
    // два вида: отчёты и уведомления сдаются, платежи оплачиваются
    kind: ['report', 'notice'],
    status: 'done',
    newest_first: true,
  })
  const editable = canEdit(user.role)

  const late = withOverdue ? (overdue.data?.items ?? []) : []
  const lateTotal = withOverdue ? (overdue.data?.total ?? 0) : 0
  const upTo = (days: number) =>
    (soon.data?.items ?? []).filter((task) => task.due_date <= addDays(today, days))

  const whole = tab === 'all'
  const source = whole ? everything : soon
  // в «Всё» прошедшие невыполненные уже есть в отдельном запросе
  const current: Task[] = whole
    ? (everything.data?.items ?? []).filter((task) => !isOverdue(task, today))
    : upTo(TABS.find(([key]) => key === tab)![2]!)
  const list = showLate ? [...late, ...current] : current
  const ready = !!source.data
  const cut =
    (source.data?.total ?? 0) > (source.data?.items.length ?? 0) ||
    (showLate && lateTotal > late.length)

  const error = overdue.error ?? soon.error ?? everything.error ?? submitted.error
  const organisation = (
    <select
      aria-label="Организация"
      value={company_id}
      onChange={(event) => set({ company: event.target.value || null })}
      className={`${CONTROL} min-w-0 flex-1 truncate`}
    >
      <option value="">Все организации</option>
      {companies.data?.map((company) => (
        <option key={company.id} value={company.id}>
          {company.short_name || company.name}
        </option>
      ))}
    </select>
  )

  if (showSubmitted) {
    const done = submitted.data?.items ?? []
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-bold">Сданные отчёты</h1>
        <Button variant="secondary" onClick={() => set({ submitted: null })}>
          ← К задачам
        </Button>
        <div className="flex gap-2">{organisation}</div>
        <ErrorText error={error} />
        {submitted.data && submitted.data.total > done.length && (
          <Alert kind="warning">Показаны последние. Выберите организацию.</Alert>
        )}
        {submitted.data && (
          <TaskFeed
            key={`submitted|${company_id}`}
            // лента сама разворачивает порядок: новые окажутся сверху
            tasks={[...done].reverse()}
            today={today}
            editable={editable}
            newestFirst
          />
        )}
      </div>
    )
  }

  return (
    <div className="space-y-4 pb-20">
      <h1 className="text-2xl font-bold">
        {ready ? headline(tab, current.length, status) : 'Задачи'}
      </h1>
      {lateTotal > 0 && (
        <div className="flex items-center gap-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm font-semibold text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
          <span className="min-w-0 flex-1">
            {lateTotal}{' '}
            {plural(lateTotal, ['срок уже прошёл', 'срока уже прошли', 'сроков уже прошли'])}
          </span>
          <button
            type="button"
            aria-expanded={showLate}
            className="cursor-pointer py-1 underline"
            onClick={() => set({ late: showLate ? null : '1' })}
          >
            {showLate ? 'Скрыть' : 'Показать'}
          </button>
        </div>
      )}
      {editable && <SubstitutionNotice userId={user.id} />}
      <button
        type="button"
        onClick={() => set({ submitted: '1' })}
        className={`${CONTROL} flex w-full cursor-pointer items-center gap-2 font-medium`}
      >
        <span aria-hidden="true" className="font-bold text-green-600">
          ✓
        </span>
        Сданные отчёты
        {submitted.data && <span className="ml-auto">{submitted.data.total}</span>}
      </button>
      <div
        role="tablist"
        aria-label="Период"
        className="grid grid-cols-4 gap-1 rounded-2xl bg-slate-200/60 p-1 dark:bg-slate-800/60"
      >
        {TABS.map(([key, title, days]) => {
          const count = days === null || !soon.data ? null : upTo(days).length
          return (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={tab === key}
              onClick={() => set({ tab: key })}
              // на узком экране число переносится под название
              className={`flex min-w-0 cursor-pointer flex-col items-center justify-center rounded-xl py-1.5 text-sm font-semibold whitespace-nowrap sm:flex-row sm:gap-1 sm:py-2.5 ${
                tab === key
                  ? 'bg-white shadow-sm dark:bg-slate-900'
                  : 'text-slate-500 dark:text-slate-400'
              }`}
            >
              {title}
              {count !== null && (
                <span className={tab === key ? 'text-blue-700 dark:text-blue-300' : ''}>
                  {count}
                </span>
              )}
            </button>
          )
        })}
      </div>
      <div className="flex gap-2">
        {organisation}
        <button
          type="button"
          aria-expanded={filtersOpen}
          onClick={() => setFiltersOpen(!filtersOpen)}
          className={`${CONTROL} cursor-pointer font-medium`}
        >
          Фильтры{filtered && ' •'} <span aria-hidden="true">{filtersOpen ? '▴' : '▾'}</span>
        </button>
      </div>
      {filtersOpen && (
        <div className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
          <Select
            label="Тип"
            value={kind}
            onChange={(event) => set({ kind: event.target.value || null })}
          >
            <option value="">Все типы</option>
            {Object.entries(KIND_NAMES).map(([key, title]) => (
              <option key={key} value={key}>
                {title}
              </option>
            ))}
          </Select>
          <Select
            label="Статус"
            value={status}
            onChange={(event) => set({ status: event.target.value })}
          >
            <option value="all">Все статусы</option>
            {Object.entries(STATUS_NAMES).map(([key, title]) => (
              <option key={key} value={key}>
                {title}
              </option>
            ))}
          </Select>
          <Button
            variant="secondary"
            disabled={!filtered}
            onClick={() => set({ kind: null, status: null })}
          >
            Сбросить
          </Button>
        </div>
      )}
      <ErrorText error={error} />
      {cut && (
        <Alert kind="warning">Показаны не все задачи. Выберите организацию или тип.</Alert>
      )}
      {ready && (
        <TaskFeed
          key={`${tab}|${company_id}|${kind}|${status}|${showLate}`}
          tasks={list}
          today={today}
          editable={editable}
          newestFirst={tab === 'all' && status !== 'planned' && status !== 'all'}
        />
      )}
      {editable && (
        <AddButton
          to={company_id ? `/tasks/new?company_id=${company_id}` : '/tasks/new'}
          label="Добавить задачу"
        />
      )}
    </div>
  )
}
