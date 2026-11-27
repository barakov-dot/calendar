import { useState } from 'react'

import { Alert, Button, Card, Checkbox, ErrorText, Field } from '../../components/ui'
import { parseOffsets } from '../../lib/format'
import type { AppSettings } from '../../lib/types'
import { useSaveSettings } from './useSettings'

export default function NotificationsTab({
  saved,
  tasks,
}: {
  saved: AppSettings['notifications']
  tasks: AppSettings['tasks']
}) {
  const [form, setForm] = useState(saved)
  const [showNotices, setShowNotices] = useState(tasks.show_notices_to_clients)
  const [offsets, setOffsets] = useState(saved.default_client_offsets_days.join(', '))
  const [signature, setSignature] = useState(saved.signature_offsets_days.join(', '))
  const signatureDays = parseOffsets(signature)
  const save = useSaveSettings()
  const change = (patch: Partial<typeof form>) => setForm({ ...form, ...patch })
  const days = parseOffsets(offsets)

  return (
    <Card title="Уведомления">
      <Field
        label="Время утреннего дайджеста (по Москве)"
        type="time"
        value={form.digest_time}
        onChange={(event) => change({ digest_time: event.target.value })}
      />
      <Checkbox
        label="Дайджест только по рабочим дням"
        checked={form.digest_workdays_only}
        onChange={(digest_workdays_only) => change({ digest_workdays_only })}
      />
      <Field
        label="Напоминать клиенту за (дней)"
        value={offsets}
        hint="Через запятую, например: 7, 3, 1"
        onChange={(event) => setOffsets(event.target.value)}
      />
      {days === null && <Alert kind="error">Укажите целые числа от 1 до 365 через запятую.</Alert>}
      <Checkbox
        label="Напоминать в день срока"
        checked={form.remind_on_due_day}
        onChange={(remind_on_due_day) => change({ remind_on_due_day })}
      />
      <Field
        label="«Заполните сумму» — за сколько рабочих дней"
        type="number"
        min={0}
        max={60}
        value={form.fill_amount_workdays_before}
        onChange={(event) => change({ fill_amount_workdays_before: Number(event.target.value) })}
      />
      <Checkbox
        label="Сообщать о просрочках"
        checked={form.overdue_notify}
        onChange={(overdue_notify) => change({ overdue_notify })}
      />
      <Field
        label="Напоминать об окончании ЭЦП за (дней)"
        value={signature}
        hint="Через запятую. В день окончания напоминание приходит всегда."
        onChange={(event) => setSignature(event.target.value)}
      />
      {signatureDays === null && (
        <Alert kind="error">Укажите целые числа от 1 до 365 через запятую.</Alert>
      )}
      <Checkbox
        label="Показывать клиентам уведомления в ФНС"
        checked={showNotices}
        onChange={setShowNotices}
      />
      <ErrorText error={save.error} />
      <Button
        disabled={days === null || signatureDays === null || save.isPending}
        onClick={() =>
          days &&
          signatureDays &&
          save.mutate({
            settings: {
              notifications: {
                ...form,
                default_client_offsets_days: days,
                signature_offsets_days: signatureDays,
              },
              tasks: { show_notices_to_clients: showNotices },
            },
          })
        }
      >
        Сохранить
      </Button>
    </Card>
  )
}
