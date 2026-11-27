import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'

import { ErrorText } from '../../components/ui'
import { api } from '../../lib/api'
import type { Demand } from '../../lib/demands'
import DemandCards from '../demands/DemandCards'

/** Требования инспекции по одной организации: открытые сверху. */
export default function CompanyDemands({
  companyId,
  editable,
}: {
  companyId: number
  editable: boolean
}) {
  const demands = useQuery({
    queryKey: ['demands', companyId],
    queryFn: () => api<Demand[]>(`/demands?company_id=${companyId}`),
    refetchOnMount: 'always',
  })
  const list = [...(demands.data ?? [])].sort((a, b) => Number(a.closed) - Number(b.closed))
  return (
    <div className="space-y-3">
      {editable && (
        <Link to={`/demands?company=${companyId}`} className="text-sm text-blue-600 underline">
          Загрузить требование
        </Link>
      )}
      <ErrorText error={demands.error} />
      {demands.data && list.length === 0 && <p className="text-sm">Требований нет.</p>}
      <DemandCards demands={list} showCompany={false} />
    </div>
  )
}
