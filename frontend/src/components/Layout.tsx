import { NavLink, Outlet } from 'react-router'

import { fullName } from '../lib/format'
import { navClass } from '../lib/navClass'
import type { User } from '../lib/types'
import { Button } from './ui'

function links(user: User): [string, string][] {
  if (user.role === 'client') return [['/', 'Главная']]
  const staff: [string, string][] = [
    ['/', 'Сегодня'],
    ['/calendar', 'Календарь'],
    ['/companies', 'Компании'],
    ['/reminders', 'Напоминания'],
  ]
  if (user.role !== 'admin') return staff
  return [...staff, ['/accountants', 'Команда'], ['/settings', 'Настройки']]
}

export default function Layout({ user, onLogout }: { user: User; onLogout: () => void }) {
  return (
    <div className="mx-auto max-w-3xl p-4">
      <header className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <nav className="flex gap-1 overflow-x-auto">
          {links(user).map(([to, title]) => (
            <NavLink key={to} to={to} end={to === '/'} className={navClass}>
              {title}
            </NavLink>
          ))}
        </nav>
        <div className="flex items-center gap-2 text-sm">
          <span className="text-slate-500 dark:text-slate-400">{fullName(user)}</span>
          <Button variant="secondary" onClick={onLogout}>
            Выйти
          </Button>
        </div>
      </header>
      <Outlet />
    </div>
  )
}
