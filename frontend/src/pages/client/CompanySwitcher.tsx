import { Alert, ErrorText, Select } from '../../components/ui'
import type { useCompanyChoice } from './useCompanyChoice'

export default function CompanySwitcher({
  choice,
}: {
  choice: ReturnType<typeof useCompanyChoice>
}) {
  const list = choice.companies.data
  return (
    <>
      <ErrorText error={choice.companies.error} />
      {list?.length === 0 && (
        <Alert>Пока нет ни одной компании. Обратитесь к бухгалтеру.</Alert>
      )}
      {list && list.length > 1 && (
        <Select
          label="Компания"
          value={choice.companyId}
          onChange={(event) => choice.choose(event.target.value)}
        >
          <option value="">Все компании</option>
          {list.map((company) => (
            <option key={company.id} value={company.id}>
              {company.short_name || company.name}
            </option>
          ))}
        </Select>
      )}
    </>
  )
}
