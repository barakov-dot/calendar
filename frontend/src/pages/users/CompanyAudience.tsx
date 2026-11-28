import { useState } from 'react'

import { Checkbox, ErrorText, Field } from '../../components/ui'
import { useCompanies } from '../../lib/useCompanies'

export type CompanyGroup = 'client' | 'accountant' | 'assistant'

const COMPANY_GROUPS: [CompanyGroup, string][] = [
  ['client', 'Клиентам этих организаций'],
  ['accountant', 'Бухгалтерам этих организаций'],
  ['assistant', 'Помощникам этих организаций'],
]

/** Рассылка по организациям: какие и кому из привязанных к ним людей. */
export default function CompanyAudience({
  ids,
  groups,
  onChange,
}: {
  ids: number[]
  groups: CompanyGroup[]
  onChange: (ids: number[], groups: CompanyGroup[]) => void
}) {
  const companies = useCompanies()
  const [search, setSearch] = useState('')
  const wanted = search.trim().toLowerCase()
  const list = (Array.isArray(companies.data) ? companies.data : []).filter(
    (company) =>
      !wanted ||
      `${company.name} ${company.short_name} ${company.inn}`.toLowerCase().includes(wanted),
  )
  const toggle = <T,>(items: T[], item: T, on: boolean) =>
    on ? [...items, item] : items.filter((other) => other !== item)

  return (
    <details open={ids.length > 0} className="space-y-2">
      <summary className="cursor-pointer text-sm font-medium">
        По организациям{ids.length > 0 && `: выбрано ${ids.length}`}
      </summary>
      <div className="space-y-2 pt-2">
        <ErrorText error={companies.error} />
        <Field
          label="Найти организацию"
          type="search"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <div className="max-h-56 space-y-2 overflow-y-auto rounded-lg border border-slate-200 p-3 dark:border-slate-700">
          {list.length === 0 && <p className="text-sm">Ничего не найдено.</p>}
          {list.map((company) => (
            <Checkbox
              key={company.id}
              label={company.short_name || company.name}
              checked={ids.includes(company.id)}
              onChange={(on) => onChange(toggle(ids, company.id, on), groups)}
            />
          ))}
        </div>
        {ids.length > 0 && (
          <fieldset className="space-y-2">
            <legend className="mb-1 text-sm font-medium">Кому из них</legend>
            {COMPANY_GROUPS.map(([group, title]) => (
              <Checkbox
                key={group}
                label={title}
                checked={groups.includes(group)}
                onChange={(on) => onChange(ids, toggle(groups, group, on))}
              />
            ))}
          </fieldset>
        )}
      </div>
    </details>
  )
}
