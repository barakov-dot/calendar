import { useMutation, useQuery } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { useSearchParams } from 'react-router'

import { Alert, Button, Card, ErrorText, Field, Select } from '../../components/ui'
import { api, apiFile } from '../../lib/api'
import { formatKopecks } from '../../lib/company'
import { saveBlob } from '../../lib/files'
import { previousMonth, todayIso } from '../../lib/tasks'
import { miniAppInitData } from '../../lib/telegram'
import { isManager } from '../../lib/roles'
import type { CompanyListItem, User } from '../../lib/types'
import { useStaff } from '../companies/useStaff'
import { type Report, type Result, RESULT_NAMES, RESULTS } from './report'
import ReportTasks from './ReportTasks'

export default function Reports({ user }: { user: User }) {
  const [inTelegram] = useState(() => miniAppInitData() !== null)
  // выбор хранится в адресе: после перехода в задачу кнопка «назад» вернёт к тому же месту
  const [params, setParams] = useSearchParams()
  const [defaults] = useState(() => previousMonth(todayIso()))
  const form = {
    from: params.get('from') ?? defaults.from,
    to: params.get('to') ?? defaults.to,
    company_id: params.get('company_id') ?? '',
    accountant_id: params.get('accountant_id') ?? '',
  }
  const shown = Number(params.get('show')) || null
  const result = RESULTS.find((key) => key === params.get('result')) ?? null
  const update = (patch: Record<string, string>) =>
    setParams(
      (before) => {
        const next = new URLSearchParams(before)
        for (const [key, value] of Object.entries(patch)) {
          // пустая дата остаётся в адресе, иначе вернулся бы период по умолчанию
          if (value === '' && key !== 'from' && key !== 'to') next.delete(key)
          else next.set(key, value)
        }
        return next
      },
      { replace: true },
    )
  const change = (patch: Partial<typeof form>) => update({ ...patch, show: '' })
  const details = useRef<HTMLDivElement>(null)
  /** Открывает задачи, посчитанные в нажатой цифре. */
  const open = (companyId: number | null, picked: Result | null) => {
    update({ show: companyId ? String(companyId) : '', result: picked ?? '' })
    details.current?.scrollIntoView?.({ behavior: 'smooth', block: 'start' })
  }
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
    queryFn: () => api<Report>(`/reports/completed?${query}`),
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

  const total = (key: Result) => preview.data?.summary.reduce((sum, row) => sum + row[key], 0) ?? 0
  const shownName = preview.data?.summary.find((row) => row.company_id === shown)?.company

  /** Цифра итогов: нажимается, если за ней есть задачи. */
  const number = (value: number, companyId: number | null, key: Result, label: string) => {
    const color = key === 'overdue' && value > 0 ? 'text-red-700 dark:text-red-300' : ''
    if (value === 0) return <span>0</span>
    return (
      <button
        type="button"
        aria-label={`${label}: ${RESULT_NAMES[key].toLowerCase()} — ${value}, показать`}
        onClick={() => open(companyId, key)}
        className={`min-w-8 rounded px-1.5 py-0.5 font-semibold underline underline-offset-2 hover:bg-slate-100 dark:hover:bg-slate-800 ${color || 'text-blue-700 dark:text-blue-300'}`}
      >
        {value}
      </button>
    )
  }

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
              {staff.data
                ?.filter((member) => member.role !== 'assistant')
                .map((member) => (
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
            <>
              <p className="text-sm text-slate-500 dark:text-slate-400">
                Нажмите на цифру или название организации, чтобы увидеть задачи.
              </p>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="text-left text-slate-500 dark:text-slate-400">
                    <tr>
                      {[
                        'Компания',
                        'Бухгалтер',
                        ...RESULTS.map((key) => RESULT_NAMES[key]),
                        'Оплачено',
                      ].map((title) => (
                        <th key={title} className="py-1 pr-3 font-medium">
                          {title}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 tabular-nums dark:divide-slate-800">
                    {preview.data.summary.map((row) => (
                      <tr key={row.company_id}>
                        <td className="py-2 pr-3">
                          <button
                            type="button"
                            onClick={() => open(row.company_id, null)}
                            className="text-left text-blue-700 underline dark:text-blue-300"
                          >
                            {row.company}
                          </button>
                        </td>
                        <td className="py-2 pr-3">{row.accountant}</td>
                        {RESULTS.map((key) => (
                          <td key={key} className="py-2 pr-3">
                            {number(row[key], row.company_id, key, row.company)}
                          </td>
                        ))}
                        <td className="py-2 whitespace-nowrap">
                          {formatKopecks(row.paid_kopecks)}
                        </td>
                      </tr>
                    ))}
                    {preview.data.summary.length > 1 && (
                      <tr className="font-medium">
                        <td className="py-2 pr-3" colSpan={2}>
                          Всего
                        </td>
                        {RESULTS.map((key) => (
                          <td key={key} className="py-2 pr-3">
                            {number(total(key), null, key, 'Всего')}
                          </td>
                        ))}
                        <td className="py-2 whitespace-nowrap">
                          {formatKopecks(
                            preview.data.summary.reduce((sum, row) => sum + row.paid_kopecks, 0),
                          )}
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </>
          )}
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Своевременность считается по дате отметки в сервисе, а не по дате платежа или отправки
            отчёта.
          </p>
        </Card>
      )}
      <div ref={details} className="scroll-mt-4">
        {preview.data && preview.data.rows.length > 0 && (
          <ReportTasks
            // новый отбор начинается с первой страницы
            key={`${query} ${shown} ${result}`}
            rows={
              shownName
                ? preview.data.rows.filter((row) => row.company_id === shown)
                : preview.data.rows
            }
            companyName={shownName ?? ''}
            result={result}
            onSelect={(picked, allCompanies) =>
              update({ result: picked ?? '', ...(allCompanies ? { show: '' } : {}) })
            }
          />
        )}
      </div>
    </div>
  )
}
