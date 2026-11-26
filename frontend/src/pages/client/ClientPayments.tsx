import { Card, ErrorText } from '../../components/ui'
import { addDays, todayIso } from '../../lib/tasks'
import { useTasks } from '../../lib/useTasks'
import ClientTasks from './ClientTasks'
import CompanySwitcher from './CompanySwitcher'
import { useCompanyChoice } from './useCompanyChoice'

export default function ClientPayments() {
  const today = todayIso()
  const choice = useCompanyChoice()
  const filters = { company_id: choice.companyId, kind: 'payment' }
  const open = useTasks({ ...filters, status: 'planned', to: addDays(today, 60) })
  const paid = useTasks({ ...filters, status: 'paid', from: addDays(today, -30) })
  const items = open.data?.items ?? []
  const overdue = items.filter((task) => task.due_date < today)

  return (
    <div className="space-y-4">
      <CompanySwitcher choice={choice} />
      <ErrorText error={open.error ?? paid.error} />
      {overdue.length > 0 && (
        <Card title="Срок прошёл">
          <ClientTasks tasks={overdue} today={today} />
        </Card>
      )}
      <Card title="К оплате">
        {open.data && (
          <ClientTasks tasks={items.filter((task) => task.due_date >= today)} today={today} />
        )}
      </Card>
      {paid.data && paid.data.items.length > 0 && (
        <Card title="Оплачено за последний месяц">
          <ClientTasks tasks={paid.data.items} today={today} />
        </Card>
      )}
    </div>
  )
}
