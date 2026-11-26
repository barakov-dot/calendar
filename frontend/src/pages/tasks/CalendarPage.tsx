import { useState } from 'react'

import TaskFilterBar, { type Filters } from '../../components/TaskFilterBar'
import TaskTable from '../../components/TaskTable'
import { Alert, Button, Card, ErrorText } from '../../components/ui'
import { formatDate } from '../../lib/company'
import { canEdit } from '../../lib/roles'
import {
  addMonths,
  monthEnd,
  monthGrid,
  monthTitle,
  todayIso,
  type Tone,
  toneOf,
} from '../../lib/tasks'
import { TONE_STYLES } from '../../lib/toneStyles'
import type { User } from '../../lib/types'
import { useTasks } from '../../lib/useTasks'

const TONES: [Tone, string][] = [
  ['overdue', 'просрочено'],
  ['planned', 'запланировано'],
  ['closed', 'выполнено'],
  ['skipped', 'не требуется'],
]

export default function CalendarPage({ user }: { user: User }) {
  const today = todayIso()
  const [month, setMonth] = useState(today.slice(0, 7))
  const [view, setView] = useState<'month' | 'list'>('month')
  const [day, setDay] = useState<string | null>(null)
  const [filters, setFilters] = useState<Filters>({ company_id: '', kind: '', status: '' })
  const tasks = useTasks({ ...filters, from: `${month}-01`, to: monthEnd(month) })
  const items = tasks.data?.items ?? []
  const editable = canEdit(user.role)
  const selected = day?.startsWith(month) ? day : null

  const move = (delta: number) => {
    setMonth(addMonths(month, delta))
    setDay(null)
  }

  return (
    <div className="space-y-4">
      <TaskFilterBar value={filters} onChange={setFilters} />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Button variant="secondary" aria-label="Предыдущий месяц" onClick={() => move(-1)}>
            ←
          </Button>
          <h1 className="min-w-40 text-center text-lg font-semibold">{monthTitle(month)}</h1>
          <Button variant="secondary" aria-label="Следующий месяц" onClick={() => move(1)}>
            →
          </Button>
        </div>
        <Button variant="secondary" onClick={() => setView(view === 'month' ? 'list' : 'month')}>
          {view === 'month' ? 'Списком' : 'Сеткой'}
        </Button>
      </div>
      <ErrorText error={tasks.error} />
      {tasks.data && tasks.data.total > items.length && (
        <Alert kind="warning">
          Показаны не все задачи месяца ({items.length} из {tasks.data.total}). Уточните фильтры.
        </Alert>
      )}
      {view === 'list' ? (
        <Card>
          <TaskTable tasks={items} today={today} editable={editable} />
        </Card>
      ) : (
        <>
          <table className="w-full table-fixed border-collapse text-center text-sm">
            <thead>
              <tr>
                {['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'].map((name) => (
                  <th key={name} className="py-1 font-medium">
                    {name}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {monthGrid(month).map((week, index) => (
                <tr key={index}>
                  {week.map((date, column) => {
                    const due = items.filter((task) => task.due_date === date)
                    return (
                      <td
                        key={date ?? column}
                        className="h-16 border border-slate-200 p-0 align-top dark:border-slate-700"
                      >
                        {date && (
                          <button
                            type="button"
                            aria-label={`${formatDate(date)}: задач ${due.length}`}
                            aria-pressed={date === selected}
                            onClick={() => setDay(date)}
                            className={`flex h-full w-full flex-col items-center gap-0.5 p-1 hover:bg-slate-100 dark:hover:bg-slate-800 ${date === selected ? 'ring-2 ring-blue-600 ring-inset' : ''}`}
                          >
                            <span className={date === today ? 'font-bold text-blue-600' : ''}>
                              {Number(date.slice(8))}
                            </span>
                            <span className="flex flex-wrap justify-center gap-0.5">
                              {TONES.map(([tone]) => {
                                const count = due.filter((t) => toneOf(t, today) === tone).length
                                return count ? (
                                  <span
                                    key={tone}
                                    className={`rounded px-1 text-xs ${TONE_STYLES[tone]}`}
                                  >
                                    {count}
                                  </span>
                                ) : null
                              })}
                            </span>
                          </button>
                        )}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
          <div className="flex flex-wrap gap-2 text-xs">
            {TONES.map(([tone, title]) => (
              <span key={tone} className={`rounded px-2 py-0.5 ${TONE_STYLES[tone]}`}>
                {title}
              </span>
            ))}
          </div>
          {selected && (
            <Card title={formatDate(selected)}>
              <TaskTable
                key={selected}
                tasks={items.filter((task) => task.due_date === selected)}
                today={today}
                editable={editable}
              />
            </Card>
          )}
        </>
      )}
    </div>
  )
}
