import { useQuery } from '@tanstack/react-query'

import { Alert, Card, ErrorText } from '../../components/ui'
import { api } from '../../lib/api'
import { formatDateTime } from '../../lib/format'
import type { BotStatus } from '../../lib/types'

const STATES = {
  connected: ['success', 'Подключён'],
  connecting: ['info', 'Подключается…'],
  error: ['warning', 'Ошибка связи, идут повторные попытки'],
  unavailable: ['error', 'Telegram недоступен дольше 5 минут'],
  problem: ['error', 'Не может подключиться'],
  stopped: ['error', 'Процесс бота не отвечает'],
  unknown: ['info', 'Статус пока неизвестен'],
} as const

export default function BotStatusCard() {
  const status = useQuery({
    queryKey: ['bot-status'],
    queryFn: () => api<BotStatus>('/admin/bot-status'),
    refetchInterval: 5000,
  })
  const data = status.data
  return (
    <Card title="Статус бота">
      <ErrorText error={status.error} />
      {data && (
        <>
          <Alert kind={STATES[data.state][0]}>
            {STATES[data.state][1]}
            {data.username && ` — @${data.username}`}
          </Alert>
          <ul className="text-sm text-slate-600 dark:text-slate-300">
            {data.problem && <li>{data.problem}</li>}
            {data.state !== 'unknown' && <li>Прокси: {data.proxy ?? 'не используется'}</li>}
            {data.last_success_at && (
              <li>Последний успешный запрос: {formatDateTime(data.last_success_at)}</li>
            )}
            {data.last_error && <li className="break-words">Ошибка: {data.last_error}</li>}
          </ul>
        </>
      )}
    </Card>
  )
}
