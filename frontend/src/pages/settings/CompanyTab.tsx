import { useState } from 'react'

import { Button, Card, ErrorText, Field } from '../../components/ui'
import type { AppSettings } from '../../lib/types'
import { useSaveSettings } from './useSettings'

export default function CompanyTab({ saved }: { saved: AppSettings['company'] }) {
  const [form, setForm] = useState(saved)
  const save = useSaveSettings()
  const bind = (name: keyof typeof form) => ({
    value: form[name],
    onChange: (event: { target: { value: string } }) =>
      setForm({ ...form, [name]: event.target.value }),
  })

  return (
    <Card title="Компания">
      <Field label="Название" {...bind('name')} />
      <Field
        label="Контакт поддержки"
        hint="Показывается клиентам, например @username"
        {...bind('support_contact')}
      />
      <Field label="Часовой пояс" {...bind('timezone')} />
      <Field
        label="Политика обработки персональных данных (ссылка)"
        type="url"
        hint="Бот показывает её вместе с запросом согласия"
        {...bind('privacy_policy_url')}
      />
      <ErrorText error={save.error} />
      <Button
        disabled={save.isPending}
        onClick={() => save.mutate({ settings: { company: form } })}
      >
        Сохранить
      </Button>
    </Card>
  )
}
