import { useState } from 'react'
import { Link } from 'react-router'

import AddButton from '../../components/AddButton'
import { BellIcon, ChevronIcon } from '../../components/Icons'
import TaskFeed from '../../components/TaskFeed'
import { Alert, Checkbox, ErrorText } from '../../components/ui'
import { todayIso } from '../../lib/tasks'
import { useTasks } from '../../lib/useTasks'

/** Личные задачи сотрудника, не связанные с организациями. */
export default function MyTasks() {
  const today = todayIso()
  const [closed, setClosed] = useState(false)
  const tasks = useTasks({ mine: true })
  const items = tasks.data?.items ?? []
  const shown = items.filter((task) => (task.status === 'planned') !== closed)

  return (
    <div className="space-y-4 pb-20">
      <h1 className="text-2xl font-bold">Мои дела</h1>
      <Link
        to="/reminders"
        className="flex items-center gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3 dark:border-slate-800 dark:bg-slate-900"
      >
        <BellIcon className="size-5 text-blue-700 dark:text-blue-300" />
        <span className="flex-1 text-sm font-medium">Повторяющиеся напоминания</span>
        <ChevronIcon className="size-5 text-slate-400" />
      </Link>
      <Checkbox label="Показать выполненные" checked={closed} onChange={setClosed} />
      <ErrorText error={tasks.error} />
      {tasks.data && tasks.data.total > items.length && (
        <Alert kind="warning">Показаны не все дела.</Alert>
      )}
      {tasks.data && (
        <TaskFeed
          key={String(closed)}
          tasks={shown}
          today={today}
          editable
          newestFirst={closed}
        />
      )}
      <AddButton to="/tasks/new" label="Добавить дело" />
    </div>
  )
}
