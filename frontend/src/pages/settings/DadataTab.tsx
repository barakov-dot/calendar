import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'

import { Alert, Button, Card, Checkbox, ErrorText, Field } from '../../components/ui'
import { api } from '../../lib/api'
import type { AppSettings, CheckResult } from '../../lib/types'
import SecretField from './SecretField'
import { useSaveSettings } from './useSettings'

export default function DadataTab({ saved }: { saved: AppSettings['dadata'] }) {
  const [enabled, setEnabled] = useState(saved.enabled)
  const [apiKey, setApiKey] = useState('')
  const [secretKey, setSecretKey] = useState('')
  const [timeout, setTimeoutSeconds] = useState(saved.timeout_seconds)
  const save = useSaveSettings()
  const check = useMutation({
    mutationFn: () =>
      api<CheckResult>('/admin/settings/test-dadata', {
        method: 'POST',
        body: { api_key: apiKey, secret_key: secretKey },
      }),
  })

  return (
    <Card title="DaData">
      <Checkbox label="Заполнять реквизиты из DaData" checked={enabled} onChange={setEnabled} />
      {!enabled && (
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Карточки компаний будут заполняться вручную.
        </p>
      )}
      <SecretField
        label="API-ключ"
        value={apiKey}
        saved={saved.has_api_key}
        onChange={setApiKey}
        onClear={() => save.mutate({ clear: ['dadata.api_key'] })}
      />
      <SecretField
        label="Секретный ключ"
        value={secretKey}
        saved={saved.has_secret_key}
        onChange={setSecretKey}
        onClear={() => save.mutate({ clear: ['dadata.secret_key'] })}
      />
      <Field
        label="Ожидание ответа, секунд"
        type="number"
        min={1}
        max={120}
        value={timeout || ''}
        onChange={(event) => setTimeoutSeconds(Number(event.target.value))}
      />
      {check.data && (
        <Alert kind={check.data.ok ? 'success' : 'error'}>{check.data.message}</Alert>
      )}
      <ErrorText error={check.error ?? save.error} />
      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" disabled={check.isPending} onClick={() => check.mutate()}>
          Проверить
        </Button>
        <Button
          disabled={save.isPending}
          onClick={() =>
            save.mutate({
              settings: {
                dadata: {
                  enabled,
                  api_key: apiKey.trim(),
                  secret_key: secretKey.trim(),
                  timeout_seconds: timeout,
                },
              },
            })
          }
        >
          Сохранить
        </Button>
      </div>
    </Card>
  )
}
