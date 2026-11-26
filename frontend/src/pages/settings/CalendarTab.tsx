import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { ChangeEvent } from 'react'

import { Alert, Card, ErrorText } from '../../components/ui'
import { api, ApiError } from '../../lib/api'

interface CalendarYear {
  year: number
  workdays: number
  days_off: number
  source: string
}

interface Uploaded {
  year: number
  tasks_created: number
  tasks_updated: number
}

async function upload(file: File): Promise<Uploaded> {
  let data: { year?: unknown }
  try {
    data = JSON.parse(await file.text()) as { year?: unknown }
  } catch {
    throw new ApiError(0, 'Файл не является JSON')
  }
  if (typeof data?.year !== 'number') {
    throw new ApiError(0, 'В файле нет поля year')
  }
  return api<Uploaded>(`/admin/calendar/${data.year}`, { method: 'POST', body: data })
}

export default function CalendarTab() {
  const queryClient = useQueryClient()
  const years = useQuery({
    queryKey: ['calendar-years'],
    queryFn: () => api<CalendarYear[]>('/admin/calendar'),
    refetchOnMount: 'always',
  })
  const load = useMutation({
    mutationFn: upload,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['calendar-years'] }),
  })

  function choose(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = '' // тот же файл можно выбрать повторно
    if (file && window.confirm(`Загрузить «${file.name}»? Календарь этого года будет заменён.`)) {
      load.mutate(file)
    }
  }

  return (
    <Card title="Производственный календарь">
      <ErrorText error={years.error} />
      {years.data?.length === 0 && (
        <Alert kind="warning">
          Календарь не загружен: сроки переносятся только с субботы и воскресенья.
        </Alert>
      )}
      <ul className="space-y-2 text-sm">
        {years.data?.map((item) => (
          <li key={item.year}>
            <span className="font-medium">{item.year}</span> — рабочих дней {item.workdays},
            выходных {item.days_off}
            <span className="block text-slate-500 dark:text-slate-400">{item.source}</span>
          </li>
        ))}
      </ul>
      <label className="block text-sm">
        <span className="mb-1 block font-medium">Загрузить файл на год (JSON)</span>
        <input type="file" accept=".json,application/json" onChange={choose} />
      </label>
      <p className="text-sm text-slate-500 dark:text-slate-400">
        Формат — как у файлов в каталоге data/calendar. После загрузки сроки всех компаний
        пересчитаются.
      </p>
      {load.isPending && <p className="text-sm">Загружаем и пересчитываем…</p>}
      {load.data && (
        <Alert kind="success">
          Календарь {load.data.year} загружен. Задач изменено: {load.data.tasks_updated}, создано:{' '}
          {load.data.tasks_created}.
        </Alert>
      )}
      <ErrorText error={load.error} />
    </Card>
  )
}
