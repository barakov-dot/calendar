import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes } from 'react-router'

import { Alert, Button } from './components/ui'
import Layout from './components/Layout'
import Accountants from './pages/Accountants'
import ClientCalendar from './pages/client/ClientCalendar'
import ClientHistory from './pages/client/ClientHistory'
import ClientPayments from './pages/client/ClientPayments'
import ClientTaskPage from './pages/client/ClientTaskPage'
import Preferences from './pages/Preferences'
import CompaniesList from './pages/companies/CompaniesList'
import CompanyCard from './pages/companies/CompanyCard'
import NewCompany from './pages/companies/NewCompany'
import Login from './pages/Login'
import SettingsPage from './pages/settings/SettingsPage'
import Reminders from './pages/reminders/Reminders'
import Reports from './pages/reports/Reports'
import CalendarPage from './pages/tasks/CalendarPage'
import NewTask from './pages/tasks/NewTask'
import TaskPage from './pages/tasks/TaskPage'
import Today from './pages/tasks/Today'
import { canEdit } from './lib/roles'
import { useAuth } from './useAuth'

// Страница dev-логина не попадает в прод-сборку.
const DevLogin = import.meta.env.DEV ? lazy(() => import('./pages/DevLogin')) : null

export default function App() {
  const { signedIn, user, error, logout } = useAuth()

  if (signedIn && !user) {
    return (
      <main className="mx-auto max-w-md space-y-3 p-6">
        {error ? (
          <>
            <Alert kind="error">{error.message}</Alert>
            <Button variant="secondary" onClick={logout}>
              Выйти
            </Button>
          </>
        ) : (
          <p>Загрузка…</p>
        )}
      </main>
    )
  }

  return (
    <Suspense fallback={null}>
      <Routes>
        {DevLogin && <Route path="/dev-login" element={<DevLogin />} />}
        {user ? (
          <Route element={<Layout user={user} onLogout={logout} />}>
            <Route
              index
              element={user.role === 'client' ? <ClientPayments /> : <Today user={user} />}
            />
            {user.role !== 'assistant' && (
              <Route path="preferences" element={<Preferences user={user} />} />
            )}
            {user.role === 'client' && (
              <>
                <Route path="calendar" element={<ClientCalendar />} />
                <Route path="history" element={<ClientHistory />} />
                <Route path="tasks/:id" element={<ClientTaskPage />} />
              </>
            )}
            {user.role !== 'client' && (
              <>
                <Route path="calendar" element={<CalendarPage user={user} />} />
                <Route path="reminders" element={<Reminders user={user} />} />
                <Route path="reports" element={<Reports user={user} />} />
                <Route path="tasks/:id" element={<TaskPage user={user} />} />
                <Route path="companies" element={<CompaniesList user={user} />} />
                <Route path="companies/:id" element={<CompanyCard user={user} />} />
                {canEdit(user.role) && (
                  <>
                    <Route path="tasks/new" element={<NewTask />} />
                    <Route path="companies/new" element={<NewCompany user={user} />} />
                  </>
                )}
              </>
            )}
            {user.role === 'admin' && (
              <>
                <Route path="accountants" element={<Accountants />} />
                <Route path="settings/*" element={<SettingsPage />} />
              </>
            )}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        ) : (
          <Route path="*" element={<Login />} />
        )}
      </Routes>
    </Suspense>
  )
}
