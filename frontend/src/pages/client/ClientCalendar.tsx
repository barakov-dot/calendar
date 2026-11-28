import { useState } from 'react'

import MonthGrid from '../../components/MonthGrid'
import { Button, Card, ErrorText } from '../../components/ui'
import { formatDate } from '../../lib/company'
import { addMonths, monthEnd, monthTitle, todayIso } from '../../lib/tasks'
import { useTasks } from '../../lib/useTasks'
import ClientTasks from './ClientTasks'
import CompanySwitcher from './CompanySwitcher'
import { useCompanyChoice } from './useCompanyChoice'

export default function ClientCalendar() {
  const today = todayIso()
  const choice = useCompanyChoice()
  const [month, setMonth] = useState(today.slice(0, 7))
  const [day, setDay] = useState<string | null>(null)
  const tasks = useTasks({
    company_id: choice.companyId,
    from: `${month}-01`,
    to: monthEnd(month),
  })
  const items = tasks.data?.items ?? []
  const selected = day?.startsWith(month) ? day : null
  const listed = selected ? items.filter((task) => task.due_date === selected) : items
  const payments = listed.filter((task) => task.kind === 'payment')
  const documents = listed.filter((task) => task.kind !== 'payment')
  const move = (delta: number) => {
    setMonth(addMonths(month, delta))
    setDay(null)
  }

  return (
    <div className="space-y-4">
      <CompanySwitcher choice={choice} />
      <div className="flex items-center justify-center gap-2">
        <Button variant="secondary" aria-label="Предыдущий месяц" onClick={() => move(-1)}>
          ←
        </Button>
        <h1 className="min-w-40 text-center text-lg font-semibold">{monthTitle(month)}</h1>
        <Button variant="secondary" aria-label="Следующий месяц" onClick={() => move(1)}>
          →
        </Button>
      </div>
      <ErrorText error={tasks.error} />
      <MonthGrid month={month} tasks={items} today={today} selected={selected} onSelect={setDay} />
      <Card title={selected ? formatDate(selected) : 'Весь месяц'}>
        {selected && (
          <Button variant="secondary" onClick={() => setDay(null)}>
            Показать весь месяц
          </Button>
        )}
        {listed.length === 0 && <p className="text-sm">Ничего нет.</p>}
      </Card>
      {payments.length > 0 && (
        <Card title="Платежи">
          <ClientTasks tasks={payments} today={today} />
        </Card>
      )}
      {documents.length > 0 && (
        <Card title="Уведомления и отчёты">
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Это не платежи: документы сдаются в инспекцию и фонды, платить по ним не нужно.
          </p>
          <ClientTasks tasks={documents} today={today} />
        </Card>
      )}
    </div>
  )
}
