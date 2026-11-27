import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router'

import FileDrop from '../../components/FileDrop'
import { Alert, Button, Card, ErrorText } from '../../components/ui'
import { api } from '../../lib/api'
import { formatDate, formatKopecks } from '../../lib/company'
import { useRefreshTasks } from '../../lib/useTasks'

export interface Declaration {
  company_id: number
  company_name: string
  inn: string
  title: string
  correction: number
  totals: { label: string; kopecks: number }[]
  parts: {
    task_id: number
    title: string
    due_date: string
    current_kopecks: number | null
    new_kopecks: number
    kept: string
  }[]
  warnings: string[]
}

/** Загрузка декларации: суммы платежей берутся из XML и записываются после проверки. */
export default function Declarations() {
  const [files, setFiles] = useState<{ id: number; file: File }[]>([])
  const add = (chosen: File[]) =>
    setFiles((before) => {
      const next = (before[0]?.id ?? 0) + 1
      // новые сверху
      return [...chosen.map((file, i) => ({ id: next + i, file })).reverse(), ...before]
    })

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Декларации</h1>
      <p className="text-sm">
        Загрузите XML декларации по НДС или по прибыли из учётной программы: сервис найдёт
        организацию по ИНН и впишет суммы в платежи. Сначала вы увидите, что изменится. НДС и
        ежемесячные авансы по прибыли делятся на три равных платежа с округлением до рубля вверх.
      </p>
      <FileDrop
        title="Перетащите XML сюда или нажмите, чтобы выбрать"
        hint="Основной файл декларации, без книг покупок и продаж. Можно сразу несколько. Файл не сохраняется."
        accept=".xml,text/xml,application/xml"
        onFiles={add}
      />
      {files.map(({ id, file }) => (
        <Loaded key={id} id={id} file={file} />
      ))}
    </div>
  )
}

function Loaded({ id, file }: { id: number; file: File }) {
  const refresh = useRefreshTasks()
  const preview = useQuery({
    queryKey: ['declaration', id, file.name, file.size, file.lastModified],
    queryFn: () => api<Declaration>('/declarations/preview', { method: 'POST', file }),
    staleTime: Infinity,
    gcTime: 0,
  })
  const apply = useMutation({
    mutationFn: () => api<Declaration>('/declarations/apply', { method: 'POST', file }),
    onSuccess: refresh,
  })
  // после записи показывается то, что сделано, а не предпросмотр
  const data = apply.data ?? preview.data

  if (!data) {
    return (
      <Card title={file.name}>
        {preview.isPending ? <p className="text-sm">Читаем файл…</p> : null}
        <ErrorText error={preview.error} />
      </Card>
    )
  }

  const changes = data.parts.filter((part) => !part.kept)
  const done = apply.isSuccess
  return (
    <Card title={data.company_name}>
      <p className="text-sm">
        {data.title}
        {data.correction > 0 && `, корректировка № ${data.correction}`} · ИНН {data.inn}
        <span className="block break-all text-slate-500 dark:text-slate-400">{file.name}</span>
      </p>
      <dl className="text-sm">
        {data.totals.map((total) => (
          <div key={total.label} className="flex flex-wrap justify-between gap-x-3">
            <dt>{total.label}</dt>
            <dd className="font-semibold tabular-nums">{formatKopecks(total.kopecks)}</dd>
          </div>
        ))}
      </dl>
      {data.warnings.map((warning) => (
        <Alert key={warning} kind="warning">
          {warning}
        </Alert>
      ))}
      <ul className="divide-y divide-slate-200 text-sm dark:divide-slate-700">
        {data.parts.map((part) => (
          <li key={part.task_id} className="py-2">
            <Link to={`/tasks/${part.task_id}`} className="font-medium text-blue-600 underline">
              {part.title}
            </Link>
            <span className="block text-slate-500 dark:text-slate-400">
              срок {formatDate(part.due_date)}
            </span>
            <span className="block tabular-nums">
              {part.kept ? (
                <span className="text-amber-700 dark:text-amber-300">
                  Не меняется: {part.kept}
                  {part.current_kopecks != null && ` (${formatKopecks(part.current_kopecks)})`}
                </span>
              ) : (
                <>
                  {part.current_kopecks != null &&
                    part.current_kopecks !== part.new_kopecks &&
                    `${formatKopecks(part.current_kopecks)} → `}
                  {formatKopecks(part.new_kopecks)}
                </>
              )}
            </span>
          </li>
        ))}
      </ul>
      <ErrorText error={apply.error} />
      {done ? (
        <Alert kind="success">Суммы записаны. Платежей изменено: {changes.length}.</Alert>
      ) : changes.length === 0 ? (
        <Alert kind="info">Менять нечего.</Alert>
      ) : (
        <Button disabled={apply.isPending} onClick={() => apply.mutate()}>
          Вписать суммы
        </Button>
      )}
    </Card>
  )
}
