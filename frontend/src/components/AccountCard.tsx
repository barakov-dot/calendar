import { fullName } from '../lib/format'
import { ROLE_NAMES } from '../lib/roles'
import type { User } from '../lib/types'
import ThemeToggle from './ThemeToggle'
import { Button } from './ui'

/** Тема оформления, имя пользователя и выход: на телефоне — внизу «Настроек». */
export default function AccountCard({ user, onLogout }: { user: User; onLogout: () => void }) {
  return (
    <div className="space-y-3 rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm font-medium">Тема оформления</span>
        <ThemeToggle />
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0 text-sm">
          <div className="truncate font-medium">{fullName(user)}</div>
          <div className="text-slate-500 dark:text-slate-400">{ROLE_NAMES[user.role]}</div>
        </div>
        <Button variant="secondary" onClick={onLogout}>
          Выйти
        </Button>
      </div>
    </div>
  )
}
