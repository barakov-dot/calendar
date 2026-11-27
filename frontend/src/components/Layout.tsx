import { NavLink, Outlet, useLocation } from 'react-router'

import { fullName } from '../lib/format'
import { navClass } from '../lib/navClass'
import { ROLE_NAMES } from '../lib/roles'
import type { User } from '../lib/types'
import ThemeToggle from './ThemeToggle'
import { Button } from './ui'

function links(user: User): [string, string][] {
  if (user.role === 'client') {
    return [
      ['/', 'Платежи'],
      ['/calendar', 'Календарь'],
      ['/history', 'История'],
      ['/preferences', 'Настройки'],
    ]
  }
  const staff: [string, string][] = [
    ['/', 'Сегодня'],
    ['/calendar', 'Календарь'],
    ['/companies', 'Компании'],
    ['/reminders', 'Напоминания'],
    ['/reports', 'Отчёты'],
  ]
  if (user.role === 'assistant') return staff
  staff.push(['/preferences', 'Уведомления'])
  if (user.role !== 'admin') return staff
  return [...staff, ['/accountants', 'Команда'], ['/settings', 'Настройки']]
}

/** На широком экране меню слева, на телефоне — сверху. */
export default function Layout({ user, onLogout }: { user: User; onLogout: () => void }) {
  // клиенту хватает узкой колонки, сотрудникам нужна ширина, настройкам — вся
  const settings = useLocation().pathname.startsWith('/settings')
  const width = user.role === 'client' ? 'max-w-3xl' : settings ? '' : 'max-w-6xl'
  return (
    <div className="min-h-screen lg:flex">
      <header className="border-b border-slate-200 bg-white lg:sticky lg:top-0 lg:flex lg:h-screen lg:w-60 lg:shrink-0 lg:flex-col lg:border-r lg:border-b-0 dark:border-slate-800 dark:bg-slate-900">
        <div className="hidden px-4 pt-5 pb-2 text-sm font-semibold lg:block">
          Платёжный календарь
        </div>
        <nav className="flex gap-1 overflow-x-auto p-2 lg:flex-col lg:overflow-visible">
          {links(user).map(([to, title]) => (
            <NavLink key={to} to={to} end={to === '/'} className={navClass}>
              {title}
            </NavLink>
          ))}
        </nav>
        <div className="flex flex-wrap items-center justify-between gap-2 px-3 pb-2 text-sm lg:mt-auto lg:flex-col lg:items-start lg:border-t lg:border-slate-200 lg:py-3 lg:dark:border-slate-800">
          <div className="min-w-0">
            <div className="truncate font-medium">{fullName(user)}</div>
            <div className="text-xs text-slate-500 dark:text-slate-400">
              {ROLE_NAMES[user.role]}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <ThemeToggle />
            <Button variant="secondary" onClick={onLogout}>
              Выйти
            </Button>
          </div>
        </div>
      </header>
      <main className={`mx-auto w-full min-w-0 flex-1 p-3 sm:p-5 ${width}`}>
        <Outlet />
      </main>
    </div>
  )
}
