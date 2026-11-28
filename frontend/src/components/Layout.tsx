import type { ComponentType } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router'

import { useDemands } from '../lib/demands'
import { fullName } from '../lib/format'
import { navClass } from '../lib/navClass'
import { canEdit, isManager, ROLE_NAMES } from '../lib/roles'
import { dayTitle, todayIso } from '../lib/tasks'
import type { User } from '../lib/types'
import { needsAttention, useCompanies } from '../lib/useCompanies'
import {
  BellIcon,
  BuildingIcon,
  CalendarIcon,
  CheckSquareIcon,
  DemandIcon,
  GearIcon,
  KeyIcon,
  ListIcon,
  ReportIcon,
  SendIcon,
  UploadIcon,
  UsersIcon,
} from './Icons'
import TelegramBack from './TelegramBack'
import ThemeToggle from './ThemeToggle'
import { Button } from './ui'

interface Entry {
  to: string
  title: string
  Symbol: ComponentType<{ className?: string }>
  badge?: number
  /** Что означает число на пункте. */
  badgeLabel?: string
  /** Другие адреса, на которых пункт тоже подсвечен. */
  also?: string[]
}

/** Разделы, открываемые из «Настроек». */
const INSIDE_MORE = ['/preferences', '/accountants', '/settings']
/** На широком экране эти разделы есть в самом меню, на телефоне — в «Настройках». */
const IN_SIDEBAR = ['/signatures', '/declarations', '/reminders', '/reports', '/users', '/broadcasts']

function Badge({ count, label = 'требуют внимания' }: { count?: number; label?: string }) {
  return count ? (
    <span
      aria-label={`${label}: ${count}`}
      className="min-w-5 rounded-full bg-orange-600 px-1.5 text-center text-xs font-semibold text-white"
    >
      {count}
    </span>
  ) : null
}

/** Сотрудник: на широком экране меню слева, на телефоне — снизу. */
function StaffLayout({ user, onLogout }: { user: User; onLogout: () => void }) {
  const path = useLocation().pathname
  const companies = useCompanies()
  const today = todayIso()
  const attention = companies.data?.filter(needsAttention).length
  const demands = useDemands()
  const open = Array.isArray(demands.data)
    ? demands.data.filter((demand) => !demand.closed).length
    : 0

  const shared: Entry[] = [
    { to: '/', title: 'Задачи', Symbol: ListIcon },
    { to: '/calendar', title: 'Календарь', Symbol: CalendarIcon },
    // помощник ничего не создаёт, личных дел у него нет
    ...(canEdit(user.role) ? [{ to: '/my', title: 'Мои дела', Symbol: CheckSquareIcon }] : []),
    {
      to: '/demands',
      title: 'Требования',
      Symbol: DemandIcon,
      badge: open,
      badgeLabel: 'открытых требований',
      also: ['/demands/'],
    },
  ]
  const organisations: Entry = {
    to: '/companies',
    title: 'Организации',
    Symbol: BuildingIcon,
    badge: attention,
  }
  // на телефоне эти разделы открываются из «Настроек»
  const wide: Entry[] = [
    ...(canEdit(user.role)
      ? [{ to: '/declarations', title: 'Декларации', Symbol: UploadIcon }]
      : []),
    { to: '/signatures', title: 'ЭЦП', Symbol: KeyIcon },
    { to: '/reminders', title: 'Напоминания', Symbol: BellIcon },
    { to: '/reports', title: 'Отчёты', Symbol: ReportIcon },
    ...(isManager(user.role)
      ? [
          { to: '/users', title: 'Пользователи', Symbol: UsersIcon, also: ['/users/'] },
          { to: '/broadcasts', title: 'Рассылка', Symbol: SendIcon },
        ]
      : []),
  ]
  const more: Entry = { to: '/more', title: 'Настройки', Symbol: GearIcon, also: INSIDE_MORE }
  // на телефоне «Организации» открываются из «Настроек», и число переносится туда
  const phone: Entry[] = [
    ...shared,
    { ...more, badge: attention, also: [...INSIDE_MORE, ...IN_SIDEBAR, '/companies'] },
  ]

  const inside = (entry: Entry) => entry.also?.some((prefix) => path.startsWith(prefix)) ?? false

  return (
    <div className="min-h-screen lg:flex">
      <aside className="hidden border-r border-slate-200 bg-white lg:sticky lg:top-0 lg:flex lg:h-screen lg:w-60 lg:shrink-0 lg:flex-col dark:border-slate-800 dark:bg-slate-900">
        <div className="px-4 pt-5 pb-2 text-sm font-semibold">Платёжный календарь</div>
        <nav aria-label="Разделы" className="flex flex-col gap-1 p-2">
          {[...shared, organisations, ...wide, more].map((entry) => (
            <NavLink
              key={entry.to}
              to={entry.to}
              end={entry.to === '/'}
              className={({ isActive }) =>
                `${navClass({ isActive: isActive || inside(entry) })} !flex items-center gap-2`
              }
            >
              <entry.Symbol className="size-5" />
              <span className="flex-1">{entry.title}</span>
              <Badge count={entry.badge} label={entry.badgeLabel} />
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto flex flex-col items-start gap-2 border-t border-slate-200 px-3 py-3 text-sm dark:border-slate-800">
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
      </aside>
      <div className="min-w-0 flex-1">
        <header className="flex flex-wrap items-baseline gap-x-3 px-4 pt-3 lg:hidden">
          <span className="font-bold">Платёжный календарь</span>
          <span className="text-sm text-slate-500 dark:text-slate-400">
            {dayTitle(today, today)}
          </span>
        </header>
        <main className="w-full min-w-0 p-3 pb-24 sm:p-5 sm:pb-24 lg:pb-5">
          <Outlet />
        </main>
      </div>
      <nav
        aria-label="Нижнее меню"
        className="fixed inset-x-0 bottom-0 z-40 flex border-t border-slate-200 bg-white pb-[env(safe-area-inset-bottom)] lg:hidden dark:border-slate-800 dark:bg-slate-900"
      >
        {phone.map((entry) => (
          <NavLink
            key={entry.to}
            to={entry.to}
            end={entry.to === '/'}
            className={({ isActive }) =>
              `flex min-w-0 flex-auto flex-col items-center gap-0.5 px-0.5 py-2 text-[11px] font-medium ${
                isActive || inside(entry)
                  ? 'text-blue-700 dark:text-blue-300'
                  : 'text-slate-500 dark:text-slate-400'
              }`
            }
          >
            <span className="relative">
              <entry.Symbol />
              <span className="absolute -top-1 left-4">
                <Badge count={entry.badge} label={entry.badgeLabel} />
              </span>
            </span>
            {entry.title}
          </NavLink>
        ))}
      </nav>
    </div>
  )
}

const CLIENT_LINKS: [string, string][] = [
  ['/', 'Платежи'],
  ['/calendar', 'Календарь'],
  ['/history', 'История'],
  ['/demands', 'Требования'],
  ['/preferences', 'Настройки'],
]

/** Клиент: короткое меню сверху, на широком экране — слева. */
function ClientLayout({ user, onLogout }: { user: User; onLogout: () => void }) {
  return (
    <div className="min-h-screen lg:flex">
      <header className="border-b border-slate-200 bg-white lg:sticky lg:top-0 lg:flex lg:h-screen lg:w-60 lg:shrink-0 lg:flex-col lg:border-r lg:border-b-0 dark:border-slate-800 dark:bg-slate-900">
        <div className="hidden px-4 pt-5 pb-2 text-sm font-semibold lg:block">
          Платёжный календарь
        </div>
        <nav className="flex gap-1 overflow-x-auto p-2 lg:flex-col lg:overflow-visible">
          {CLIENT_LINKS.map(([to, title]) => (
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
      <main className="w-full min-w-0 flex-1 p-3 sm:p-5">
        <Outlet />
      </main>
    </div>
  )
}

export default function Layout(props: { user: User; onLogout: () => void }) {
  const client = props.user.role === 'client'
  return (
    <>
      <TelegramBack client={client} />
      {client ? <ClientLayout {...props} /> : <StaffLayout {...props} />}
    </>
  )
}
