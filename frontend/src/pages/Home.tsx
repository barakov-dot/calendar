import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'

import { Card, ErrorText } from '../components/ui'
import { api } from '../lib/api'
import type { Role, User } from '../lib/types'

const ROLE_NAMES: Record<Role, string> = {
  admin: 'администратор',
  accountant: 'бухгалтер',
  client: 'клиент',
}

export default function Home({ user }: { user: User }) {
  return (
    <div className="space-y-4">
      <Card title="Платёжный календарь">
        <p>Вы вошли как {ROLE_NAMES[user.role]}.</p>
        {user.role !== 'client' && (
          <Link to="/companies" className="text-blue-600 underline">
            Перейти к компаниям
          </Link>
        )}
        <p className="text-slate-500 dark:text-slate-400">
          Календарь сроков появится в следующих версиях.
        </p>
      </Card>
      {user.role === 'client' && <ClientCompanies />}
    </div>
  )
}

function ClientCompanies() {
  const companies = useQuery({
    queryKey: ['companies'],
    queryFn: () =>
      api<{ id: number; inn: string; name: string; short_name: string }[]>('/companies'),
  })
  return (
    <Card title="Ваши компании">
      <ErrorText error={companies.error} />
      {companies.data?.length === 0 && (
        <p className="text-sm">Пока нет ни одной. Обратитесь к бухгалтеру.</p>
      )}
      <ul className="space-y-1">
        {companies.data?.map((company) => (
          <li key={company.id}>
            {company.short_name || company.name}
            <span className="text-slate-500 dark:text-slate-400"> · ИНН {company.inn}</span>
          </li>
        ))}
      </ul>
    </Card>
  )
}
