import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { Alert, Button, Card, Checkbox, ErrorText, Field } from '../components/ui'
import { api } from '../lib/api'
import { parseOffsets } from '../lib/format'
import type { User } from '../lib/types'

interface Preferences {
  offsets_days: number[] | null
  on_due_day: boolean | null
  daily_digest: boolean
  digest_time: string | null
  defaults: { offsets_days: number[]; on_due_day: boolean; digest_time: string }
}

interface Contacts {
  support_contact: string
  accountants: { company: string; accountant: string; username: string }[]
}

const URL = '/me/notification-settings'

export default function PreferencesPage({ user }: { user: User }) {
  const preferences = useQuery({
    queryKey: ['preferences'],
    queryFn: () => api<Preferences>(URL),
    refetchOnMount: 'always',
  })
  const client = user.role === 'client'
  return (
    <div className="space-y-4">
      <ErrorText error={preferences.error} />
      {preferences.data && (
        <Form key={JSON.stringify(preferences.data)} saved={preferences.data} client={client} />
      )}
      {client && <ContactsCard />}
    </div>
  )
}

function Form({ saved, client }: { saved: Preferences; client: boolean }) {
  const queryClient = useQueryClient()
  const { defaults } = saved
  const [offsets, setOffsets] = useState((saved.offsets_days ?? defaults.offsets_days).join(', '))
  const [onDay, setOnDay] = useState(saved.on_due_day ?? defaults.on_due_day)
  const [digest, setDigest] = useState(saved.daily_digest)
  const [time, setTime] = useState(saved.digest_time ?? '')
  const days = parseOffsets(offsets)
  const save = useMutation({
    mutationFn: () => {
      // сервер принимает только сами настройки, без значений по умолчанию
      const current = {
        offsets_days: saved.offsets_days,
        on_due_day: saved.on_due_day,
        daily_digest: saved.daily_digest,
        digest_time: saved.digest_time,
      }
      return api<Preferences>(URL, {
        method: 'PUT',
        body: client
          ? { ...current, offsets_days: days, on_due_day: onDay }
          : { ...current, daily_digest: digest, digest_time: time || null },
      })
    },
    onSuccess: (data) => queryClient.setQueryData(['preferences'], data),
  })

  return (
    <Card title="Уведомления">
      {client ? (
        <>
          <Field
            label="Напоминать о платеже за (дней)"
            value={offsets}
            hint="Через запятую. Пусто — не напоминать заранее."
            onChange={(event) => setOffsets(event.target.value)}
          />
          {days === null && (
            <Alert kind="error">Укажите целые числа от 1 до 365 через запятую.</Alert>
          )}
          <Checkbox label="Напоминать в день срока" checked={onDay} onChange={setOnDay} />
        </>
      ) : (
        <>
          <Checkbox label="Присылать утренний дайджест" checked={digest} onChange={setDigest} />
          <Field
            label="Время дайджеста (по Москве)"
            type="time"
            value={time}
            hint={`Пусто — как по умолчанию (${defaults.digest_time})`}
            onChange={(event) => setTime(event.target.value)}
          />
        </>
      )}
      <ErrorText error={save.error} />
      <Button disabled={(client && days === null) || save.isPending} onClick={() => save.mutate()}>
        Сохранить
      </Button>
    </Card>
  )
}

function ContactsCard() {
  const contacts = useQuery({
    queryKey: ['contacts'],
    queryFn: () => api<Contacts>('/me/contacts'),
  })
  return (
    <Card title="Связаться">
      <ErrorText error={contacts.error} />
      <ul className="space-y-1 text-sm">
        {contacts.data?.accountants.map((item) => (
          <li key={item.company}>
            {item.company}: {item.accountant}
            {item.username && (
              <>
                {' — '}
                <a
                  href={`https://t.me/${item.username}`}
                  target="_blank"
                  rel="noreferrer"
                  className="text-blue-600 underline"
                >
                  @{item.username}
                </a>
              </>
            )}
          </li>
        ))}
      </ul>
      {contacts.data?.support_contact && (
        <p className="text-sm">Поддержка: {contacts.data.support_contact}</p>
      )}
    </Card>
  )
}
