import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'

import App from './App'
import './index.css'
import { session } from './lib/api'
import { announceMiniAppReady, miniAppInitData } from './lib/telegram'
import { applyTheme } from './lib/theme'

// Внутри Telegram вход всегда по initData: на устройстве мог сменить аккаунт.
if (miniAppInitData()) {
  session.clear()
  announceMiniAppReady()
}

applyTheme()

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
