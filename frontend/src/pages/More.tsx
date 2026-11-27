import type { ComponentType } from 'react'
import { Link } from 'react-router'

import {
  BellIcon,
  BuildingIcon,
  ChevronIcon,
  GearIcon,
  ReportIcon,
  SendIcon,
  UploadIcon,
  UsersIcon,
} from '../components/Icons'
import ThemeToggle from '../components/ThemeToggle'
import { Button } from '../components/ui'
import { fullName } from '../lib/format'
import { canEdit, ROLE_NAMES } from '../lib/roles'
import type { User } from '../lib/types'
import { needsAttention, useCompanies } from '../lib/useCompanies'

type Item = [string, string, string, ComponentType<{ className?: string }>]

function items(user: User): Item[] {
  const list: Item[] = [
    ['/companies', 'Организации', 'Карточки, клиенты, налоги и подписи', BuildingIcon],
  ]
  if (canEdit(user.role)) {
    list.push(
      ['/declarations', 'Декларации', 'Суммы НДС и прибыли из XML', UploadIcon],
      ['/preferences', 'Уведомления', 'Что и когда присылает бот', BellIcon],
    )
  }
  list.push(
    ['/reminders', 'Напоминания', 'Свои повторяющиеся задачи', BellIcon],
    ['/reports', 'Отчёты', 'Что выполнено за период: Excel и PDF', ReportIcon],
  )
  if (user.role === 'admin') {
    list.push(
      ['/users', 'Пользователи', 'Все, кто подключён: карточки и имена', UsersIcon],
      ['/broadcasts', 'Рассылка', 'Сообщение от бота выбранным людям', SendIcon],
      ['/accountants', 'Команда', 'Сотрудники, приглашения, замещения', UsersIcon],
      ['/settings', 'Настройки сервиса', 'Telegram, DaData, сроки, копии', GearIcon],
    )
  }
  return list
}

/** Раздел «Настройки»: всё, что не помещается в нижнее меню. */
export default function More({ user, onLogout }: { user: User; onLogout: () => void }) {
  const attention = useCompanies().data?.filter(needsAttention).length
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Настройки</h1>
      <ul className="divide-y divide-slate-100 overflow-hidden rounded-xl border border-slate-200 bg-white dark:divide-slate-800 dark:border-slate-800 dark:bg-slate-900">
        {items(user).map(([to, title, hint, Symbol]) => (
          <li key={to} className={to === '/companies' ? 'lg:hidden' : ''}>
            <Link
              to={to}
              className="flex items-center gap-3 px-4 py-3 hover:bg-slate-50 dark:hover:bg-slate-800/50"
            >
              <Symbol className="size-6 shrink-0 text-blue-700 dark:text-blue-300" />
              <span className="min-w-0 flex-1">
                <span className="block font-medium">{title}</span>
                <span className="block text-sm text-slate-500 dark:text-slate-400">{hint}</span>
                {to === '/companies' && !!attention && (
                  <span className="block text-sm font-medium text-orange-700 dark:text-orange-300">
                    Требуют внимания: {attention}
                  </span>
                )}
              </span>
              <ChevronIcon className="size-5 shrink-0 text-slate-400" />
            </Link>
          </li>
        ))}
      </ul>
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
    </div>
  )
}
