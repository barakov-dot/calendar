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
  /** Файл передаётся телом запроса, имя — в заголовке. */
  file?: File
}

async function send(path: string, { method = 'GET', body, file }: Options, token?: string) {
  const headers: Record<string, string> = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (file) {
    headers['Content-Type'] = 'application/octet-stream'
    headers['X-Filename'] = encodeURIComponent(file.name)
  }
  if (token) headers.Authorization = `Bearer ${token}`
  try {
    return await fetch(`/api${path}`, {
      method,
      headers,
      body: file ?? (body === undefined ? undefined : JSON.stringify(body)),
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

/** При истёкшем access-токене один раз обновляет его и повторяет запрос. */
async function request(path: string, options: Options): Promise<Response> {
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
  return response
}

/** Запрос к API. */
export async function api<T>(path: string, options: Options = {}): Promise<T> {
  return read<T>(await request(path, options))
}

/** Скачивание файла. */
export async function apiFile(path: string): Promise<Blob> {
  const response = await request(path, {})
  if (!response.ok) await read(response) // бросает понятную ошибку
  return response.blob()
}
