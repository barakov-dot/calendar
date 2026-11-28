import { useState } from 'react'

import { Alert, Button, Card, Checkbox, ErrorText, Field } from '../../components/ui'
import { parseOffsets } from '../../lib/format'
import type { AppSettings } from '../../lib/types'
import { useSaveSettings } from './useSettings'

const DEMAND_RECIPIENTS = [
  ['demand_notify_admin', 'Администратору'],
  ['demand_notify_chief', 'Главному бухгалтеру'],
  ['demand_notify_accountants', 'Бухгалтерам организации'],
  ['demand_notify_assistants', 'Помощникам организации'],
  ['demand_notify_clients', 'Клиентам'],
] as const

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
  const [receipt, setReceipt] = useState(saved.demand_receipt_offsets_days.join(', '))
  const [response, setResponse] = useState(saved.demand_response_offsets_days.join(', '))
  const receiptDays = parseOffsets(receipt, 0, 60)
  const responseDays = parseOffsets(response, 0, 60)
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
        label="Присылать помощникам напоминания о сроках по их организациям"
        checked={form.assistant_reminders}
        onChange={(assistant_reminders) => change({ assistant_reminders })}
      />
      <h3 className="pt-2 font-semibold">Требования инспекции</h3>
      <Field
        label="Квитанция о приёме: напоминать за (рабочих дней)"
        value={receipt}
        hint="Через запятую. 0 — в сам день."
        onChange={(event) => setReceipt(event.target.value)}
      />
      <Field
        label="Ответ, оплата или явка: напоминать за (рабочих дней)"
        value={response}
        hint="Через запятую. 0 — в сам день."
        onChange={(event) => setResponse(event.target.value)}
      />
      {(receiptDays === null || responseDays === null) && (
        <Alert kind="error">Укажите целые числа от 0 до 60 через запятую.</Alert>
      )}
      <fieldset className="space-y-2">
        <legend className="mb-1 text-sm font-medium">Кому напоминать о требованиях</legend>
        {DEMAND_RECIPIENTS.map(([key, label]) => (
          <Checkbox
            key={key}
            label={label}
            checked={form[key]}
            onChange={(checked) => change({ [key]: checked })}
          />
        ))}
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Администратор и главный бухгалтер получают напоминания по всем организациям, бухгалтеры
          и помощники — по своим. Клиентам напоминают только о сроке исполнения.
        </p>
      </fieldset>
      <h3 className="pt-2 font-semibold">Прочее</h3>
      <Checkbox
        label="Показывать клиентам уведомления в ФНС"
        checked={showNotices}
        onChange={setShowNotices}
      />
      <Checkbox
        label="Напоминать мне, если нет свежей резервной копии"
        checked={form.backup_alert}
        onChange={(backup_alert) => change({ backup_alert })}
      />
      <p className="text-sm text-slate-500 dark:text-slate-400">
        Сервис видит только копии, созданные командой make backup. Если вы копируете весь
        сервер другим способом, выключите.
      </p>
      <ErrorText error={save.error} />
      <Button
        disabled={
          days === null ||
          signatureDays === null ||
          receiptDays === null ||
          responseDays === null ||
          save.isPending
        }
        onClick={() =>
          days &&
          signatureDays &&
          receiptDays &&
          responseDays &&
          save.mutate({
            settings: {
              notifications: {
                ...form,
                default_client_offsets_days: days,
                signature_offsets_days: signatureDays,
                demand_receipt_offsets_days: receiptDays,
                demand_response_offsets_days: responseDays,
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
