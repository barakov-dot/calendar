import { useMutation } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link } from 'react-router'

import { Alert, Button, Card, ErrorText } from '../components/ui'
import { api, ApiError, session, type Tokens } from '../lib/api'
import { miniAppInitData } from '../lib/telegram'

const POLL_MS = 2000

interface LoginRequest {
  nonce: string
  code: string
  deeplink: string
}

export default function Login() {
  const [initData] = useState(miniAppInitData)
  return (
    <main className="mx-auto flex min-h-screen max-w-sm flex-col justify-center p-4">
      <Card title="Платёжный календарь">
        {initData ? <MiniAppLogin initData={initData} /> : <SiteLogin />}
        {import.meta.env.DEV && !initData && (
          <Link to="/dev-login" className="block text-sm text-blue-600 underline">
            Вход для разработки
          </Link>
        )}
      </Card>
    </main>
  )
}

function MiniAppLogin({ initData }: { initData: string }) {
  const login = useMutation({
    mutationFn: () =>
      api<Tokens>('/auth/telegram-webapp', { method: 'POST', body: { init_data: initData } }),
    onSuccess: (tokens) => session.set(tokens),
  })
  const { mutate } = login
  useEffect(() => mutate(), [mutate])

  if (!login.error) return <p>Входим…</p>
  return (
    <>
      <ErrorText error={login.error} />
      <Button onClick={() => mutate()}>Повторить</Button>
    </>
  )
}

function SiteLogin() {
  const start = useMutation({
    mutationFn: () => api<LoginRequest>('/auth/login-request', { method: 'POST' }),
  })

  if (start.data) {
    return (
      <Waiting key={start.data.nonce} request={start.data} onRestart={() => start.mutate()} />
    )
  }
  return (
    <>
      <p className="text-sm">Вход по приглашению, через Telegram-бота.</p>
      <ErrorText error={start.error} />
      <Button onClick={() => start.mutate()} disabled={start.isPending}>
        Войти через Telegram
      </Button>
    </>
  )
}

function Waiting({ request, onRestart }: { request: LoginRequest; onRestart: () => void }) {
  const [failure, setFailure] = useState<string | null>(null)

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>
    let stopped = false
    async function poll() {
      try {
        const result = await api<{ status: string; tokens: Tokens | null }>(
          `/auth/poll/${request.nonce}`,
        )
        if (result.tokens) {
          session.set(result.tokens)
          return
        }
      } catch (error) {
        // обрыв связи не прерывает ожидание, отказ сервера — прерывает
        if (error instanceof ApiError && error.status !== 0 && error.status < 500) {
          if (!stopped) setFailure(error.message)
          return
        }
      }
      if (!stopped) timer = setTimeout(poll, POLL_MS)
    }
    timer = setTimeout(poll, POLL_MS)
    return () => {
      stopped = true
      clearTimeout(timer)
    }
  }, [request.nonce])

  if (failure) {
    return (
      <>
        <Alert kind="error">{failure}</Alert>
        <Button onClick={onRestart}>Начать заново</Button>
      </>
    )
  }
  return (
    <>
      <p className="text-sm">
        Откройте бота, нажмите «Запустить», сверьте код и подтвердите вход.
      </p>
      <p className="text-center text-3xl font-semibold tracking-widest">{request.code}</p>
      <a
        href={request.deeplink}
        target="_blank"
        rel="noreferrer"
        className="block rounded-lg bg-blue-600 px-4 py-2 text-center text-sm font-medium text-white"
      >
        Открыть бота
      </a>
      <p className="text-sm text-slate-500 dark:text-slate-400">Ждём подтверждения…</p>
    </>
  )
}
