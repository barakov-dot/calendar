export interface Tokens {
  access_token: string
  refresh_token: string
}

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

const KEY = 'buh.tokens'
const listeners = new Set<() => void>()

export const session = {
  get(): Tokens | null {
    try {
      return JSON.parse(localStorage.getItem(KEY) ?? 'null') as Tokens | null
    } catch {
      return null
    }
  },
  set(tokens: Tokens) {
    localStorage.setItem(KEY, JSON.stringify(tokens))
    listeners.forEach((listener) => listener())
  },
  clear() {
    localStorage.removeItem(KEY)
    listeners.forEach((listener) => listener())
  },
  subscribe(listener: () => void) {
    listeners.add(listener)
    return () => {
      listeners.delete(listener)
    }
  },
}

interface Options {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'
  body?: unknown
}

async function send(path: string, { method = 'GET', body }: Options, token?: string) {
  const headers: Record<string, string> = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (token) headers.Authorization = `Bearer ${token}`
  try {
    return await fetch(`/api${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ApiError(0, 'Нет связи с сервером')
  }
}

async function read<T>(response: Response): Promise<T> {
  if (response.status === 204) return undefined as T
  const data: unknown = await response.json().catch(() => null)
  if (response.ok) return data as T
  const detail = (data as { detail?: unknown } | null)?.detail
  throw new ApiError(
    response.status,
    typeof detail === 'string'
      ? detail
      : response.status === 422
        ? 'Проверьте введённые значения'
        : `Ошибка сервера (${response.status})`,
  )
}

let refreshing: Promise<boolean> | null = null

async function refresh(): Promise<boolean> {
  const tokens = session.get()
  if (!tokens) return false
  const response = await send('/auth/refresh', {
    method: 'POST',
    body: { refresh_token: tokens.refresh_token },
  })
  if (response.status === 401) {
    session.clear()
    return false
  }
  session.set(await read<Tokens>(response))
  return true
}

/** Запрос к API. При истёкшем access-токене один раз обновляет его и повторяет запрос. */
export async function api<T>(path: string, options: Options = {}): Promise<T> {
  let response = await send(path, options, session.get()?.access_token)
  if (response.status === 401 && session.get()) {
    // параллельные запросы ждут одно общее обновление
    refreshing ??= refresh().finally(() => {
      refreshing = null
    })
    if (await refreshing) {
      response = await send(path, options, session.get()?.access_token)
    }
  }
  return read<T>(response)
}
