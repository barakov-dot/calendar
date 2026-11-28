import type { ComponentType } from 'react'
import { Link } from 'react-router'

import AccountCard from '../components/AccountCard'
import {
  BellIcon,
  BuildingIcon,
  ChevronIcon,
  GearIcon,
  KeyIcon,
  ReportIcon,
  SendIcon,
  UploadIcon,
  UsersIcon,
} from '../components/Icons'
import { canEdit, isManager } from '../lib/roles'
import type { User } from '../lib/types'
import { needsAttention, useCompanies } from '../lib/useCompanies'

type Item = [string, string, string, ComponentType<{ className?: string }>]

function items(user: User): Item[] {
  const list: Item[] = [
    ['/companies', 'Организации', 'Карточки, клиенты, налоги и подписи', BuildingIcon],
  ]
  if (canEdit(user.role)) {
    list.push(
      ['/declarations', 'Декларации', 'Суммы из XML: НДС, прибыль, УСН', UploadIcon],
      ['/preferences', 'Уведомления', 'Что и когда присылает бот', BellIcon],
    )
  }
  list.push(
    ['/signatures', 'ЭЦП', 'Сроки электронных подписей', KeyIcon],
    ['/reminders', 'Напоминания', 'Свои повторяющиеся задачи', BellIcon],
    ['/reports', 'Отчёты', 'Что выполнено за период: Excel и PDF', ReportIcon],
  )
  if (isManager(user.role)) {
    list.push(
      ['/users', 'Пользователи', 'Все, кто подключён: карточки и имена', UsersIcon],
      ['/broadcasts', 'Рассылка', 'Сообщение от бота выбранным людям', SendIcon],
      ['/accountants', 'Команда', 'Сотрудники, приглашения, замещения', UsersIcon],
    )
  }
  if (user.role === 'admin') {
    list.push(['/settings', 'Настройки сервиса', 'Telegram, DaData, сроки, копии', GearIcon])
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
      <AccountCard user={user} onLogout={onLogout} />
    </div>
  )
}
