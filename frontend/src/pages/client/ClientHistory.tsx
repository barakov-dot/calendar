import { Card, ErrorText } from '../../components/ui'
import { addDays, todayIso } from '../../lib/tasks'
import { useTasks } from '../../lib/useTasks'
import ClientTasks from './ClientTasks'
import CompanySwitcher from './CompanySwitcher'
import { useCompanyChoice } from './useCompanyChoice'

export default function ClientHistory() {
  const today = todayIso()
  const choice = useCompanyChoice()
  const tasks = useTasks({ company_id: choice.companyId, from: addDays(today, -365), to: today })
  // новые сверху; ещё не выполненное показывают «Платежи»
  const done = (tasks.data?.items ?? []).filter((task) => task.status !== 'planned').reverse()

  return (
    <div className="space-y-4">
      <CompanySwitcher choice={choice} />
      <ErrorText error={tasks.error} />
      <Card title="Выполнено за год">
        {tasks.data && <ClientTasks tasks={done} today={today} />}
      </Card>
    </div>
  )
}
