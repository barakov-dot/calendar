import { useState } from 'react'

import TextArea from '../../components/TextArea'
import { Button, Card, ErrorText } from '../../components/ui'
import { useSaveSettings } from './useSettings'

/** Список «на кого выпущена ЭЦП» для выбора в карточке компании. */
export default function SignatureHoldersCard({ saved }: { saved: string[] }) {
  const [text, setText] = useState(saved.join('\n'))
  const save = useSaveSettings()
  const list = text
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)

  return (
    <Card title="Электронные подписи">
      <TextArea label="На кого выпускают ЭЦП, по одному в строке" value={text} onChange={setText} />
      <p className="text-sm text-slate-500 dark:text-slate-400">
        Из этого списка выбирают при добавлении подписи. Первый вариант выбран сразу. Уже
        добавленные подписи не меняются.
      </p>
      <ErrorText error={save.error} />
      <Button
        disabled={save.isPending || list.join('\n') === saved.join('\n')}
        onClick={() => save.mutate({ settings: { company: { signature_holders: list } } })}
      >
        Сохранить список
      </Button>
    </Card>
  )
}
