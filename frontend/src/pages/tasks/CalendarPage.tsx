import { useState } from 'react'

import MonthGrid from '../../components/MonthGrid'
import TaskFilterBar, { type Filters } from '../../components/TaskFilterBar'
import TaskTable from '../../components/TaskTable'
import { Alert, Button, Card, ErrorText } from '../../components/ui'
import { formatDate } from '../../lib/company'
import { canEdit } from '../../lib/roles'
import { addMonths, monthEnd, monthTitle, todayIso } from '../../lib/tasks'
import type { User } from '../../lib/types'
import { useTasks } from '../../lib/useTasks'

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
        <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
          <div className="space-y-2">
            <MonthGrid
              month={month}
              tasks={items}
              today={today}
              selected={selected}
              onSelect={setDay}
            />
          </div>
          <Card title={selected ? formatDate(selected) : 'Выберите день'}>
            {selected ? (
              <TaskTable
                key={selected}
                tasks={items.filter((task) => task.due_date === selected)}
                today={today}
                editable={editable}
              />
            ) : (
              <p className="text-sm text-slate-500 dark:text-slate-400">
                Нажмите на день в календаре, чтобы увидеть задачи.
              </p>
            )}
          </Card>
        </div>
      )}
    </div>
  )
}
