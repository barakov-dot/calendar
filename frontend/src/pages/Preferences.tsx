import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import AccountCard from '../components/AccountCard'
import TelegramLink from '../components/TelegramLink'
import { Alert, Button, Card, Checkbox, ErrorText, Select } from '../components/ui'
import { api } from '../lib/api'
import { TIME_ZONES, timeOptions } from '../lib/reminderTimes'
import type { User } from '../lib/types'
import { userTarget } from '../lib/telegramLinks'
import OffsetList from './preferences/OffsetList'

interface Preferences {
  offsets_days: number[] | null
  on_due_day: boolean | null
  daily_digest: boolean
  digest_time: string | null
  timezone: string | null
  defaults: { offsets_days: number[]; on_due_day: boolean; digest_time: string; timezone: string }
}

interface Contacts {
  support_contact: string
  accountants: { company: string; accountant: string; username: string; substitute?: boolean }[]
}

const URL = '/me/notification-settings'

export default function PreferencesPage({
  user,
  onLogout,
}: {
  user: User
  onLogout: () => void
}) {
  const preferences = useQuery({
    queryKey: ['preferences'],
    queryFn: () => api<Preferences>(URL),
    refetchOnMount: 'always',
  })
  const client = user.role === 'client'
  // форма пересоздаётся после сохранения, а подтверждение должно остаться
  const [justSaved, setJustSaved] = useState(false)
  return (
    <div className="mx-auto w-full max-w-xl space-y-4">
      <ErrorText error={preferences.error} />
      {preferences.data && (
        <Form
          key={JSON.stringify(preferences.data)}
          saved={preferences.data}
          client={client}
          justSaved={justSaved}
          onSaved={() => setJustSaved(true)}
        />
      )}
      {client && <ContactsCard />}
      {/* на широком экране это есть в боковом меню */}
      {client && (
        <div className="lg:hidden">
          <AccountCard user={user} onLogout={onLogout} />
        </div>
      )}
    </div>
  )
}

function Form({
  saved,
  client,
  justSaved,
  onSaved,
}: {
  saved: Preferences
  client: boolean
  justSaved: boolean
  onSaved: () => void
}) {
  const queryClient = useQueryClient()
  const { defaults } = saved
  const initial = {
    offsets: saved.offsets_days ?? defaults.offsets_days,
    onDay: saved.on_due_day ?? defaults.on_due_day,
    digest: saved.daily_digest,
    time: saved.digest_time ?? defaults.digest_time,
    zone: saved.timezone ?? defaults.timezone,
  }
  const [form, setForm] = useState(initial)
  const change = (patch: Partial<typeof form>) => setForm({ ...form, ...patch })
  const dirty = JSON.stringify(form) !== JSON.stringify(initial)
  const save = useMutation({
    mutationFn: () => {
      // не изменённое остаётся «как по умолчанию» и следует за настройками сервиса
      const body: Omit<Preferences, 'defaults'> = {
        offsets_days: form.offsets === initial.offsets ? saved.offsets_days : form.offsets,
        on_due_day: form.onDay === initial.onDay ? saved.on_due_day : form.onDay,
        daily_digest: form.digest,
        digest_time: form.time === initial.time ? saved.digest_time : form.time,
        timezone: form.zone === initial.zone ? saved.timezone : form.zone,
      }
      return api<Preferences>(URL, { method: 'PUT', body })
    },
    onSuccess: (data) => {
      onSaved()
      queryClient.setQueryData(['preferences'], data)
    },
  })
  // пояс компании может не входить в список
  const zones = TIME_ZONES.some(([key]) => key === form.zone)
    ? TIME_ZONES
    : [...TIME_ZONES, [form.zone, form.zone] as [string, string]]

  return (
    <Card title="Утренние сообщения">
      <p className="text-sm text-slate-500 dark:text-slate-400">
        В выбранное время бот присылает напоминания {client ? 'о платежах' : 'о сроках'}. Нет
        сроков — нет и сообщений.
      </p>
      <div className="grid grid-cols-2 gap-3">
        <Select
          label="Время"
          value={form.time}
          onChange={(event) => change({ time: event.target.value })}
        >
          {timeOptions(form.time).map((time) => (
            <option key={time}>{time}</option>
          ))}
        </Select>
        <Select
          label="Часовой пояс"
          value={form.zone}
          onChange={(event) => change({ zone: event.target.value })}
        >
          {zones.map(([key, name]) => (
            <option key={key} value={key}>
              {name}
            </option>
          ))}
        </Select>
      </div>
      <hr className="border-slate-200 dark:border-slate-800" />
      {client ? (
        <OffsetList
          days={form.offsets}
          onDueDay={form.onDay}
          onChange={(offsets, onDay) => change({ offsets, onDay })}
        />
      ) : (
        <Checkbox
          label="Присылать утренний дайджест"
          checked={form.digest}
          onChange={(digest) => change({ digest })}
        />
      )}
      <ErrorText error={save.error} />
      {justSaved && !dirty && <Alert kind="success">Сохранено.</Alert>}
      <Button disabled={!dirty || save.isPending} onClick={() => save.mutate()}>
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
          <li key={`${item.company} ${item.accountant}`}>
            {item.company}: {item.accountant}
            {item.substitute && ' (замещает бухгалтера)'}
            {item.username && (
              <>
                {' — '}
                <TelegramLink to={userTarget(item.username)} className="text-blue-600 underline">
                  @{item.username}
                </TelegramLink>
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
