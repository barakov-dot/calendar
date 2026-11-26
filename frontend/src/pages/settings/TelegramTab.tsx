import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'

import { Alert, Button, Card, Checkbox, ErrorText, Field } from '../../components/ui'
import { api } from '../../lib/api'
import type { AppSettings, CheckResult, ProxyForm } from '../../lib/types'
import BotStatusCard from './BotStatusCard'
import SecretField from './SecretField'
import { useSaveSettings } from './useSettings'

function toForm(saved: AppSettings['telegram']['proxy']): ProxyForm {
  const { enabled, host, port, username, rdns } = saved
  return { enabled, host, port, username, rdns, password: '' }
}

export default function TelegramTab({ saved }: { saved: AppSettings['telegram'] }) {
  const [proxy, setProxy] = useState(() => toForm(saved.proxy))
  const [botUsername, setBotUsername] = useState(saved.bot_username)
  const [miniAppUrl, setMiniAppUrl] = useState(saved.mini_app_url)
  const save = useSaveSettings()
  const check = useMutation({
    mutationFn: (body: ProxyForm) =>
      api<CheckResult>('/admin/settings/test-proxy', { method: 'POST', body }),
  })

  const change = (patch: Partial<ProxyForm>) => setProxy({ ...proxy, ...patch })
  const proxyChanged = JSON.stringify(proxy) !== JSON.stringify(toForm(saved.proxy))
  // результат проверки действует, только пока поля не менялись
  const checkIsCurrent = JSON.stringify(check.variables) === JSON.stringify(proxy)
  const verified = checkIsCurrent && check.data?.ok === true
  const dirty =
    proxyChanged || botUsername !== saved.bot_username || miniAppUrl !== saved.mini_app_url

  const submit = () =>
    save.mutate({
      settings: {
        telegram: { bot_username: botUsername, mini_app_url: miniAppUrl, proxy },
      },
    })

  return (
    <div className="space-y-4">
      <BotStatusCard />
      <Card title="Прокси SOCKS5">
        <Checkbox
          label="Подключаться через прокси"
          checked={proxy.enabled}
          onChange={(enabled) => change({ enabled })}
        />
        {!proxy.enabled && (
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Если выключено, используется TELEGRAM_PROXY_URL из .env, а без него — прямое
            подключение.
          </p>
        )}
        <div className="grid gap-4 sm:grid-cols-[1fr_8rem]">
          <Field
            label="Хост"
            value={proxy.host}
            onChange={(event) => change({ host: event.target.value.trim() })}
          />
          <Field
            label="Порт"
            type="number"
            min={1}
            max={65535}
            value={proxy.port || ''}
            onChange={(event) => change({ port: Number(event.target.value) })}
          />
        </div>
        <Field
          label="Логин"
          autoComplete="off"
          value={proxy.username}
          onChange={(event) => change({ username: event.target.value })}
        />
        <SecretField
          label="Пароль"
          value={proxy.password}
          saved={saved.proxy.has_password}
          onChange={(password) => change({ password })}
          onClear={() => save.mutate({ clear: ['telegram.proxy.password'] })}
        />
        <Checkbox
          label="Разрешать имена через прокси (rdns)"
          checked={proxy.rdns}
          onChange={(rdns) => change({ rdns })}
        />
        <Button variant="secondary" disabled={check.isPending} onClick={() => check.mutate(proxy)}>
          {check.isPending ? 'Проверяем…' : 'Проверить подключение'}
        </Button>
        {checkIsCurrent && check.data && (
          <Alert kind={check.data.ok ? 'success' : 'error'}>
            {check.data.ok ? '✓ ' : '✗ '}
            {check.data.message}
          </Alert>
        )}
        {checkIsCurrent && <ErrorText error={check.error} />}
      </Card>
      <Card title="Бот и Mini App">
        <Field
          label="Имя бота"
          value={botUsername}
          hint="Нужно, только пока бот ни разу не подключался"
          onChange={(event) => setBotUsername(event.target.value)}
        />
        <Field
          label="Адрес Mini App"
          type="url"
          value={miniAppUrl}
          onChange={(event) => setMiniAppUrl(event.target.value)}
        />
      </Card>
      <ErrorText error={save.error} />
      <div className="flex flex-wrap gap-2">
        <Button disabled={!dirty || (proxyChanged && !verified) || save.isPending} onClick={submit}>
          Сохранить
        </Button>
        {proxyChanged && !verified && (
          <Button
            variant="secondary"
            disabled={save.isPending}
            onClick={() => {
              if (window.confirm('Сохранить прокси без проверки? Бот может потерять связь.')) {
                submit()
              }
            }}
          >
            Сохранить без проверки
          </Button>
        )}
      </div>
    </div>
  )
}
