import { formatDateTime } from '../lib/format'
import { shareTarget } from '../lib/telegramLinks'
import type { Invite } from '../lib/types'
import TelegramLink from './TelegramLink'
import { Button } from './ui'

const KINDS: Record<string, string> = {
  chief: 'главный бухгалтер,',
  accountant: 'бухгалтер,',
  assistant: 'помощник,',
}
const MESSAGE =
  'Приглашение в платёжный календарь. Нажмите на ссылку, затем «Запустить». Ссылка одноразовая.'

/** Действующие приглашения: отправка, копирование и отзыв. */
export default function InviteList({
  invites,
  onRevoke,
}: {
  invites: Invite[]
  onRevoke: (id: number) => void
}) {
  return (
    <ul className="space-y-3">
      {invites.map((item) => (
        <li key={item.id} className="space-y-2">
          <input
            readOnly
            aria-label="Ссылка-приглашение"
            value={item.link}
            onFocus={(event) => event.target.select()}
            className="w-full rounded-lg border border-slate-300 bg-transparent px-3 py-2 text-sm dark:border-slate-600"
          />
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <TelegramLink
              to={shareTarget(item.link, MESSAGE)}
              className="rounded-lg bg-blue-600 px-4 py-2 font-medium text-white hover:bg-blue-700"
            >
              Отправить в Telegram
            </TelegramLink>
            <Button variant="secondary" onClick={() => navigator.clipboard?.writeText(item.link)}>
              Копировать
            </Button>
            <Button variant="danger" onClick={() => onRevoke(item.id)}>
              Отозвать
            </Button>
            <span className="text-slate-500 dark:text-slate-400">
              {KINDS[item.kind] ?? ''} до {formatDateTime(item.expires_at)}
            </span>
          </div>
        </li>
      ))}
    </ul>
  )
}
