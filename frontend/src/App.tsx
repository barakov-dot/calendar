import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes } from 'react-router'

import { Alert, Button } from './components/ui'
import Layout from './components/Layout'
import Accountants from './pages/Accountants'
import CompaniesList from './pages/companies/CompaniesList'
import CompanyCard from './pages/companies/CompanyCard'
import NewCompany from './pages/companies/NewCompany'
import Home from './pages/Home'
import Login from './pages/Login'
import SettingsPage from './pages/settings/SettingsPage'
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
            <Route index element={<Home user={user} />} />
            {user.role !== 'client' && (
              <>
                <Route path="companies" element={<CompaniesList user={user} />} />
                <Route path="companies/new" element={<NewCompany user={user} />} />
                <Route path="companies/:id" element={<CompanyCard user={user} />} />
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
