import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router'

import TextArea from '../../components/TextArea'
import { Alert, Button, Card, Checkbox, ErrorText, Field, Select } from '../../components/ui'
import { api } from '../../lib/api'
import { parseRubles } from '../../lib/company'
import { KIND_NAMES, type TaskKind, todayIso } from '../../lib/tasks'
import type { CompanyListItem } from '../../lib/types'
import { useRefreshTasks } from '../../lib/useTasks'

export default function NewTask() {
  const navigate = useNavigate()
  const refresh = useRefreshTasks()
  const [params] = useSearchParams()
  const [companyId, setCompanyId] = useState(params.get('company_id') ?? '')
  const [title, setTitle] = useState('')
  const [kind, setKind] = useState<TaskKind>('other')
  const [due, setDue] = useState(todayIso())
  const [amount, setAmount] = useState('')
  const [comment, setComment] = useState('')
  const [visible, setVisible] = useState(false)
  const companies = useQuery({
    queryKey: ['companies', false, ''],
    queryFn: () => api<CompanyListItem[]>('/companies'),
  })
  const hasAmount = kind === 'payment' || kind === 'other'
  const kopecks = hasAmount ? parseRubles(amount) : null
  const create = useMutation({
    mutationFn: () =>
      api<{ id: number }>('/tasks', {
        method: 'POST',
        body: {
          company_id: companyId ? Number(companyId) : null,
          title,
          kind,
          due_date: due,
          amount_kopecks: kopecks,
          comment,
          client_visible: companyId !== '' && visible,
        },
      }),
    onSuccess: (task) => {
      refresh()
      navigate(`/tasks/${task.id}`, { replace: true })
    },
  })

  return (
    <Card title="Новая задача">
      <Select label="Компания" value={companyId} onChange={(e) => setCompanyId(e.target.value)}>
        <option value="">Личная задача</option>
        {companies.data?.map((company) => (
          <option key={company.id} value={company.id}>
            {company.short_name || company.name}
          </option>
        ))}
      </Select>
      <Field label="Название" value={title} onChange={(e) => setTitle(e.target.value)} />
      <Select label="Тип" value={kind} onChange={(e) => setKind(e.target.value as TaskKind)}>
        {Object.entries(KIND_NAMES).map(([key, name]) => (
          <option key={key} value={key}>
            {name}
          </option>
        ))}
      </Select>
      <Field label="Срок" type="date" value={due} onChange={(e) => setDue(e.target.value)} />
      {hasAmount && (
        <Field
          label="Сумма, ₽"
          inputMode="decimal"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
        />
      )}
      {kopecks === undefined && <Alert kind="error">Сумма — число, например 36 000,50.</Alert>}
      <TextArea label="Внутренний комментарий" value={comment} onChange={setComment} />
      {companyId && <Checkbox label="Клиент видит задачу" checked={visible} onChange={setVisible} />}
      <ErrorText error={create.error} />
      <Button
        disabled={!title.trim() || !due || kopecks === undefined || create.isPending}
        onClick={() => create.mutate()}
      >
        Создать задачу
      </Button>
    </Card>
  )
}
