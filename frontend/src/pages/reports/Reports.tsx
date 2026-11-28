import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { Alert, Button, Card, ErrorText, Field, Select } from '../../components/ui'
import { api, apiFile } from '../../lib/api'
import { formatKopecks } from '../../lib/company'
import { saveBlob } from '../../lib/files'
import { previousMonth, todayIso } from '../../lib/tasks'
import { miniAppInitData } from '../../lib/telegram'
import { isManager } from '../../lib/roles'
import type { CompanyListItem, User } from '../../lib/types'
import { useStaff } from '../companies/useStaff'

interface Preview {
  summary: {
    accountant: string
    company: string
    on_time: number
    late: number
    not_required: number
    overdue: number
    paid_kopecks: number
  }[]
  tasks: number
}

export default function Reports({ user }: { user: User }) {
  const [inTelegram] = useState(() => miniAppInitData() !== null)
  const [form, setForm] = useState(() => ({
    ...previousMonth(todayIso()),
    company_id: '',
    accountant_id: '',
  }))
  const change = (patch: Partial<typeof form>) => setForm({ ...form, ...patch })
  const companies = useQuery({
    queryKey: ['companies', false, ''],
    queryFn: () => api<CompanyListItem[]>('/companies'),
  })
  const staff = useStaff(isManager(user.role))
  const query = new URLSearchParams(
    Object.entries(form).filter(([, value]) => value !== ''),
  ).toString()
  const ready = form.from !== '' && form.to >= form.from
  const preview = useQuery({
    queryKey: ['report', query],
    queryFn: () => api<Preview>(`/reports/completed?${query}`),
    enabled: ready,
    refetchOnMount: 'always',
  })
  const download = useMutation({
    mutationFn: async (format: 'xlsx' | 'pdf') =>
      saveBlob(
        await apiFile(`/reports/completed.${format}?${query}`),
        `report-${form.from}-${form.to}.${format}`,
      ),
  })
  const send = useMutation({
    mutationFn: (format: 'xlsx' | 'pdf') =>
      api(`/reports/completed.${format}/send?${query}`, { method: 'POST' }),
  })

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Отчёт о выполненном</h1>
      <Card>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Field
            label="С"
            type="date"
            value={form.from}
            onChange={(event) => change({ from: event.target.value })}
          />
          <Field
            label="По"
            type="date"
            value={form.to}
            onChange={(event) => change({ to: event.target.value })}
          />
          <Select
            label="Компания"
            value={form.company_id}
            onChange={(event) => change({ company_id: event.target.value })}
          >
            <option value="">Все</option>
            {companies.data?.map((company) => (
              <option key={company.id} value={company.id}>
                {company.short_name || company.name}
              </option>
            ))}
          </Select>
          {isManager(user.role) && (
            <Select
              label="Бухгалтер"
              value={form.accountant_id}
              onChange={(event) => change({ accountant_id: event.target.value })}
            >
              <option value="">Все</option>
              {staff.data?.filter((member) => member.role !== 'assistant').map((member) => (
                <option key={member.id} value={member.id}>
                  {member.name}
                </option>
              ))}
            </Select>
          )}
        </div>
        {!ready && <Alert kind="error">Укажите период: конец не раньше начала.</Alert>}
        <div className="flex flex-wrap gap-2">
          {(['xlsx', 'pdf'] as const).map((format) => {
            const title = format === 'xlsx' ? 'Excel' : 'PDF'
            return (
              <span key={format} className="flex gap-2">
                {!inTelegram && (
                  <Button
                    disabled={!ready || download.isPending}
                    onClick={() => download.mutate(format)}
                  >
                    Скачать {title}
                  </Button>
                )}
                <Button
                  variant="secondary"
                  disabled={!ready || send.isPending}
                  onClick={() => send.mutate(format)}
                >
                  {title} в Telegram
                </Button>
              </span>
            )
          })}
        </div>
        <ErrorText error={download.error ?? send.error} />
        {send.isSuccess && <Alert kind="success">Отчёт отправлен вам в чат с ботом.</Alert>}
      </Card>
      <ErrorText error={preview.error} />
      {preview.data && (
        <Card title={`Итоги · задач: ${preview.data.tasks}`}>
          {preview.data.summary.length === 0 ? (
            <p className="text-sm">За этот период нет ни выполненных, ни просроченных задач.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-slate-500 dark:text-slate-400">
                  <tr>
                    {['Компания', 'Бухгалтер', 'В срок', 'С опозданием', 'Не требуется', 'Просрочено', 'Оплачено'].map(
                      (title) => (
                        <th key={title} className="py-1 pr-3 font-medium">
                          {title}
                        </th>
                      ),
                    )}
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 tabular-nums dark:divide-slate-800">
                  {preview.data.summary.map((row) => (
                    <tr key={`${row.company} ${row.accountant}`}>
                      <td className="py-2 pr-3">{row.company}</td>
                      <td className="py-2 pr-3">{row.accountant}</td>
                      <td className="py-2 pr-3">{row.on_time}</td>
                      <td className="py-2 pr-3">{row.late}</td>
                      <td className="py-2 pr-3">{row.not_required}</td>
                      <td
                        className={`py-2 pr-3 ${row.overdue > 0 ? 'font-semibold text-red-700 dark:text-red-300' : ''}`}
                      >
                        {row.overdue}
                      </td>
                      <td className="py-2 whitespace-nowrap">{formatKopecks(row.paid_kopecks)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Своевременность считается по дате отметки в сервисе, а не по дате платежа или отправки
            отчёта.
          </p>
        </Card>
      )}
    </div>
  )
}
