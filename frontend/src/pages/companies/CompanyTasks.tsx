import { useState } from 'react'
import { Link } from 'react-router'

import TaskTable from '../../components/TaskTable'
import { Alert, Card, ErrorText, Select } from '../../components/ui'
import { addDays, todayIso } from '../../lib/tasks'
import { useTasks } from '../../lib/useTasks'

type Period = 'attention' | 'upcoming' | 'all'

export default function CompanyTasks({
  companyId,
  editable,
}: {
  companyId: number
  editable: boolean
}) {
  const today = todayIso()
  const [period, setPeriod] = useState<Period>('upcoming')
  const ranges = {
    attention: { to: addDays(today, -1), status: 'planned' },
    upcoming: { from: today, to: addDays(today, 60) },
    all: {},
  }
  const tasks = useTasks({ company_id: companyId, ...ranges[period] })

  return (
    <Card title="Задачи">
      <Select label="Показать" value={period} onChange={(e) => setPeriod(e.target.value as Period)}>
        <option value="upcoming">Ближайшие 60 дней</option>
        <option value="attention">Просроченные</option>
        <option value="all">Все</option>
      </Select>
      {editable && (
        <Link to={`/tasks/new?company_id=${companyId}`} className="text-sm text-blue-600 underline">
          Добавить задачу
        </Link>
      )}
      <ErrorText error={tasks.error} />
      {tasks.data && tasks.data.total > tasks.data.items.length && (
        <Alert kind="warning">Показаны не все: {tasks.data.items.length} из {tasks.data.total}.</Alert>
      )}
      {tasks.data && (
        <TaskTable
          key={period}
          tasks={tasks.data.items}
          today={today}
          editable={editable}
          showCompany={false}
        />
      )}
    </Card>
  )
}
