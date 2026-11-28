import { useState } from 'react'

import { Button, Card, ErrorText, Field } from '../../components/ui'
import type { AppSettings } from '../../lib/types'
import SignatureHoldersCard from './SignatureHoldersCard'
import SiteIconCard from './SiteIconCard'
import { useSaveSettings } from './useSettings'

type Texts = Omit<AppSettings['company'], 'signature_holders'>

export default function CompanyTab({ saved }: { saved: AppSettings['company'] }) {
  // список для подписей сохраняется своей карточкой
  const [form, setForm] = useState<Texts>(() => ({
    name: saved.name,
    support_contact: saved.support_contact,
    timezone: saved.timezone,
    privacy_policy_url: saved.privacy_policy_url,
  }))
  const save = useSaveSettings()
  const bind = (name: keyof Texts) => ({
    value: form[name],
    onChange: (event: { target: { value: string } }) =>
      setForm({ ...form, [name]: event.target.value }),
  })

  return (
    <div className="space-y-4">
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
      <SignatureHoldersCard saved={saved.signature_holders} />
      <SiteIconCard />
    </div>
  )
}
