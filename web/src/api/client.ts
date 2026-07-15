import type { Envelope } from './types'

export class ApiError extends Error {
  code: string
  status: number
  details?: Record<string, unknown>

  constructor(status: number, code: string, message: string, details?: Record<string, unknown>) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }
}

let refreshPromise: Promise<boolean> | null = null

async function tryRefresh(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = (async () => {
      const res = await fetch('/api/v1/auth/refresh', {
        method: 'POST',
        credentials: 'include',
      })
      return res.ok
    })().finally(() => {
      refreshPromise = null
    })
  }
  return refreshPromise
}

export async function apiRequest<T>(
  path: string,
  init: RequestInit = {},
  options: { retry?: boolean } = {},
): Promise<T> {
  const retry = options.retry ?? true
  const headers = new Headers(init.headers)
  if (init.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const response = await fetch(path, {
    ...init,
    headers,
    credentials: 'include',
  })

  if (
    response.status === 401 &&
    retry &&
    !path.includes('/auth/login') &&
    !path.includes('/auth/refresh')
  ) {
    const ok = await tryRefresh()
    if (ok) {
      return apiRequest<T>(path, init, { retry: false })
    }
  }

  let payload: Envelope<T> | { ok: false; error: { code: string; message: string; details?: Record<string, unknown> } }
  try {
    payload = await response.json()
  } catch {
    throw new ApiError(response.status, 'invalid_response', '响应不是有效的 JSON')
  }

  if (!response.ok || payload.ok === false) {
    const err = 'error' in payload ? payload.error : undefined
    throw new ApiError(
      response.status,
      err?.code ?? 'request_failed',
      err?.message ?? `请求失败（${response.status}）`,
      err?.details,
    )
  }

  return payload.data
}
