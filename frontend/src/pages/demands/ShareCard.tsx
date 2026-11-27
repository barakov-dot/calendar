import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import TextArea from '../../components/TextArea'
import { Alert, Button, Card, Checkbox, ErrorText } from '../../components/ui'
import { api } from '../../lib/api'
import { formatDateTime } from '../../lib/format'

export interface Recipient {
  user_id: number
  name: string
  group: 'client' | 'accountant' | 'assistant'
  reason: string | null
  status: 'pending' | 'sent' | 'failed' | 'skipped' | null
  sent_at: string | null
}

const GROUPS = [
  ['client', 'Клиенты'],
  ['accountant', 'Бухгалтер'],
  ['assistant', 'Помощники'],
] as const

const STATES = {
  pending: 'в очереди',
  sent: 'доставлено',
  failed: 'не доставлено',
  skipped: 'не отправлено: получатель больше не связан с организацией',
}

const LIMIT = 700

/** Отправка требования с документом выбранным людям через бота. */
export default function ShareCard({ demandId, hasFile }: { demandId: number; hasFile: boolean }) {
  const queryClient = useQueryClient()
  const key = ['recipients', demandId]
  const path = `/demands/${demandId}`
  const list = useQuery({
    queryKey: key,
    queryFn: () => api<Recipient[]>(`${path}/recipients`),
    refetchOnMount: 'always',
    // пока сообщения в очереди, состояние обновляется само
    refetchInterval: (query) =>
      query.state.data?.some((item) => item.status === 'pending') ? 5000 : false,
  })
  const [chosen, setChosen] = useState<ReadonlySet<number>>(new Set())
  const [comment, setComment] = useState('')
  const send = useMutation({
    mutationFn: () =>
      api<Recipient[]>(`${path}/share`, {
        method: 'POST',
        body: { user_ids: [...chosen], comment },
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(key, data)
      setChosen(new Set())
      setComment('')
    },
  })
  const toggle = (id: number) => {
    const next = new Set(chosen)
    if (!next.delete(id)) next.add(id)
    setChosen(next)
  }

  return (
    <Card title="Отправить">
      <p className="text-sm text-slate-500 dark:text-slate-400">
        Бот пришлёт {hasFile ? 'сроки, сумму и документ' : 'сроки и сумму'}. Внутренний комментарий требования
        не отправляется.
      </p>
      <ErrorText error={list.error} />
      {list.data?.length === 0 && <p className="text-sm">С организацией пока никто не связан.</p>}
      {GROUPS.map(([group, title]) => {
        const people = list.data?.filter((item) => item.group === group) ?? []
        if (people.length === 0) return null
        return (
          <fieldset key={group} className="space-y-1">
            <legend className="text-sm font-semibold">{title}</legend>
            {people.map((item) => (
              <div key={item.user_id}>
                <Checkbox
                  label={item.name}
                  checked={chosen.has(item.user_id)}
                  disabled={item.reason !== null}
                  onChange={() => toggle(item.user_id)}
                />
                <p className="pl-6 text-xs text-slate-500 dark:text-slate-400">
                  {item.reason ??
                    (item.status &&
                      `${STATES[item.status]}${item.sent_at ? ` ${formatDateTime(item.sent_at)}` : ''}`)}
                </p>
              </div>
            ))}
          </fieldset>
        )
      })}
      <TextArea label="Сообщение получателям" value={comment} onChange={setComment} />
      {comment.length > LIMIT && <Alert kind="error">Не длиннее {LIMIT} знаков.</Alert>}
      <ErrorText error={send.error} />
      <Button
        disabled={chosen.size === 0 || comment.length > LIMIT || send.isPending}
        onClick={() => send.mutate()}
      >
        Отправить в Telegram{chosen.size > 0 && ` · ${chosen.size}`}
      </Button>
    </Card>
  )
}
