import { useQuery } from '@tanstack/react-query'

import { api } from '../lib/api'
import { KIND_NAMES, STATUS_NAMES } from '../lib/tasks'
import type { CompanyListItem } from '../lib/types'
import { Select } from './ui'

export interface Filters {
  company_id: string
  kind: string
  status: string
}

export default function TaskFilterBar({
  value,
  onChange,
}: {
  value: Filters
  onChange: (filters: Filters) => void
}) {
  const companies = useQuery({
    queryKey: ['companies', false, ''],
    queryFn: () => api<CompanyListItem[]>('/companies'),
  })
  const bind = (name: keyof Filters) => ({
    value: value[name],
    onChange: (event: { target: { value: string } }) =>
      onChange({ ...value, [name]: event.target.value }),
  })
  return (
    <div className="grid gap-3 sm:grid-cols-3">
      <Select label="Компания" {...bind('company_id')}>
        <option value="">Все компании</option>
        {companies.data?.map((company) => (
          <option key={company.id} value={company.id}>
            {company.short_name || company.name}
          </option>
        ))}
      </Select>
      <Select label="Тип" {...bind('kind')}>
        <option value="">Все типы</option>
        {Object.entries(KIND_NAMES).map(([key, title]) => (
          <option key={key} value={key}>
            {title}
          </option>
        ))}
      </Select>
      <Select label="Статус" {...bind('status')}>
        <option value="">Все статусы</option>
        {Object.entries(STATUS_NAMES).map(([key, title]) => (
          <option key={key} value={key}>
            {title}
          </option>
        ))}
      </Select>
    </div>
  )
}
