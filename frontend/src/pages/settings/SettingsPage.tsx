import { useQuery } from '@tanstack/react-query'
import { Navigate, NavLink, Route, Routes } from 'react-router'

import { Alert, ErrorText } from '../../components/ui'
import { api } from '../../lib/api'
import { navClass } from '../../lib/navClass'
import type { SettingsResponse } from '../../lib/types'
import BackupsTab from './BackupsTab'
import CalendarTab from './CalendarTab'
import CompanyTab from './CompanyTab'
import DadataTab from './DadataTab'
import NotificationsTab from './NotificationsTab'
import RosstatTab from './RosstatTab'
import TelegramTab from './TelegramTab'
import { SETTINGS_KEY } from './useSettings'

const TABS = [
  ['telegram', 'Telegram и прокси'],
  ['dadata', 'DaData'],
  ['rosstat', 'Росстат'],
  ['notifications', 'Уведомления'],
  ['company', 'Компания'],
  ['calendar', 'Производственный календарь'],
  ['backups', 'Резервные копии'],
] as const

export default function SettingsPage() {
  const query = useQuery({
    queryKey: SETTINGS_KEY,
    queryFn: () => api<SettingsResponse>('/admin/settings'),
    refetchOnMount: 'always',
  })
  const settings = query.data?.settings

  return (
    <div className="space-y-4">
      {/* вкладки переносятся на новую строку, чтобы все были видны */}
      <nav className="flex flex-wrap gap-1">
        {TABS.map(([path, title]) => (
          <NavLink key={path} to={`/settings/${path}`} replace className={navClass}>
            {title}
          </NavLink>
        ))}
      </nav>
      <ErrorText error={query.error} />
      {query.data?.file_error && (
        <Alert kind="warning">
          Файл settings.json содержит ошибку и не применён, показана последняя рабочая версия.
          Сохранение перезапишет файл (его копия останется в резервных). {query.data.file_error}
        </Alert>
      )}
      {/* key пересоздаёт форму, когда сохранённые значения изменились */}
      {settings && (
        <Routes>
          <Route
            path="telegram"
            element={<TelegramTab key={JSON.stringify(settings.telegram)} saved={settings.telegram} />}
          />
          <Route
            path="dadata"
            element={<DadataTab key={JSON.stringify(settings.dadata)} saved={settings.dadata} />}
          />
          <Route
            path="notifications"
            element={
              <NotificationsTab
                key={JSON.stringify([settings.notifications, settings.tasks])}
                saved={settings.notifications}
                tasks={settings.tasks}
              />
            }
          />
          <Route
            path="company"
            element={<CompanyTab key={JSON.stringify(settings.company)} saved={settings.company} />}
          />
          <Route
            path="rosstat"
            element={<RosstatTab key={JSON.stringify(settings.rosstat)} saved={settings.rosstat} />}
          />
          <Route path="calendar" element={<CalendarTab />} />
          <Route path="backups" element={<BackupsTab />} />
          <Route path="*" element={<Navigate to="/settings/telegram" replace />} />
        </Routes>
      )}
    </div>
  )
}
