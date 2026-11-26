import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { api } from '../../lib/api'

const KEY = 'buh.company'

export interface ClientCompany {
  id: number
  inn: string
  name: string
  short_name: string
}

/** Компании клиента и выбранная из них ('' — все). Выбор запоминается. */
export function useCompanyChoice() {
  const companies = useQuery({
    queryKey: ['companies', 'client'],
    queryFn: () => api<ClientCompany[]>('/companies'),
  })
  const [stored, setStored] = useState(() => localStorage.getItem(KEY) ?? '')
  // привязку могли снять: тогда показываем все
  const known = companies.data?.some((company) => String(company.id) === stored)
  return {
    companies,
    companyId: known ? stored : '',
    choose: (id: string) => {
      localStorage.setItem(KEY, id)
      setStored(id)
    },
  }
}
