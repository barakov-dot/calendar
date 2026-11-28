import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import FileDrop from '../../components/FileDrop'
import { Alert, Button, Card, Checkbox, ErrorText, Field } from '../../components/ui'
import { api } from '../../lib/api'
import type { AppSettings } from '../../lib/types'
import { useSaveSettings } from './useSettings'

interface Status {
  has_certificate: boolean
  total: number
  checked: number
  failed: number
  errors: Record<string, number>
}

export default function RosstatTab({ saved }: { saved: AppSettings['rosstat'] }) {
  const queryClient = useQueryClient()
  const [enabled, setEnabled] = useState(saved.enabled)
  const [time, setTime] = useState(saved.search_time)
  const save = useSaveSettings()
  const status = useQuery({
    queryKey: ['rosstat-status'],
    queryFn: () => api<Status>('/admin/rosstat'),
    refetchOnMount: 'always',
    // пока организации в очереди, счётчик обновляется сам
    refetchInterval: (query) =>
      saved.enabled && query.state.data && query.state.data.checked < query.state.data.total
        ? 10_000
        : false,
  })
  const reload = () => void queryClient.invalidateQueries({ queryKey: ['rosstat-status'] })
  const upload = useMutation({
    mutationFn: (file: File) => api('/admin/rosstat/certificate', { method: 'POST', file }),
    onSuccess: reload,
  })
  const remove = useMutation({
    mutationFn: () => api('/admin/rosstat/certificate', { method: 'DELETE' }),
    onSuccess: reload,
  })
  const check = useMutation({
    mutationFn: () =>
      api<{ ok: boolean; message: string }>('/admin/rosstat/check', { method: 'POST' }),
  })
  const runAll = useMutation({
    mutationFn: () => api('/admin/rosstat/run', { method: 'POST' }),
    onSuccess: reload,
  })
  const data = status.data
  const dirty = enabled !== saved.enabled || time !== saved.search_time

  return (
    <div className="space-y-4">
      <Card title="Поиск форм Росстата">
        <p className="text-sm">
          Сервис раз в день ищет по ИНН каждой организации, какие формы статистики она должна
          сдать, и ставит сроки в календарь. ИНН передаются на сайт websbor.rosstat.gov.ru.
        </p>
        <Checkbox label="Искать формы" checked={enabled} onChange={setEnabled} />
        <Field
          label="Время ежедневного поиска (по Москве)"
          type="time"
          value={time}
          onChange={(event) => setTime(event.target.value)}
        />
        <ErrorText error={save.error} />
        <Button
          disabled={!dirty || !time || save.isPending}
          onClick={() =>
            save.mutate({
              settings: { rosstat: { ...saved, enabled, search_time: time } },
            })
          }
        >
          Сохранить
        </Button>
      </Card>

      <Card title="Сертификат сайта">
        <p className="text-sm">
          Сайт Росстата подписан удостоверяющим центром Минцифры. Скачайте «Корневой
          сертификат» на gosuslugi.ru/crt и загрузите сюда. Он используется только для
          обращений к Росстату.
        </p>
        {data && (
          <Alert kind={data.has_certificate ? 'success' : 'warning'}>
            {data.has_certificate ? 'Сертификат загружен.' : 'Сертификат не загружен.'}
          </Alert>
        )}
        <FileDrop
          title={data?.has_certificate ? 'Заменить сертификат' : 'Загрузить сертификат'}
          hint="Файл .cer, .crt или .pem"
          accept=".cer,.crt,.pem,.der"
          disabled={upload.isPending}
          onFiles={([file]) => upload.mutate(file)}
        />
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" disabled={check.isPending} onClick={() => check.mutate()}>
            {check.isPending ? 'Проверяем…' : 'Проверить подключение'}
          </Button>
          {data?.has_certificate && (
            <Button
              variant="danger"
              onClick={() => {
                if (window.confirm('Удалить сертификат?')) remove.mutate()
              }}
            >
              Удалить сертификат
            </Button>
          )}
        </div>
        {check.data && (
          <Alert kind={check.data.ok ? 'success' : 'error'}>{check.data.message}</Alert>
        )}
        <ErrorText error={upload.error ?? remove.error ?? check.error} />
      </Card>

      <Card title="Состояние">
        <ErrorText error={status.error ?? runAll.error} />
        {data && (
          <p className="text-sm">
            Проверено организаций: {data.checked} из {data.total}
            {data.failed > 0 && `, с ошибкой: ${data.failed}`}.
          </p>
        )}
        {Object.entries(data?.errors ?? {}).map(([message, count]) => (
          <Alert key={message} kind="warning">
            {message} — организаций: {count}
          </Alert>
        ))}
        <Button
          variant="secondary"
          disabled={!saved.enabled || runAll.isPending}
          onClick={() => runAll.mutate()}
        >
          Проверить все сейчас
        </Button>
        {runAll.isSuccess && (
          <Alert kind="success">
            Поставлено в очередь. Организации проверяются по одной, начиная в течение минуты.
          </Alert>
        )}
      </Card>
    </div>
  )
}
