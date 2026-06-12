// Thin fetch-based API client.
//
// Responsibilities:
//   * Prefix requests with the configured API base URL.
//   * Attach the bearer access token.
//   * Transparently refresh the access token once on a 401, then retry.
//   * Surface a typed ApiError for non-2xx responses.
//
// Tokens are persisted in localStorage. This is adequate for a LAN-first
// internal tool; revisit (httpOnly cookies) if exposed beyond the VPN.

import type { TokenPair } from '@/types'

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1'

const ACCESS_KEY = 'helios.access_token'
const REFRESH_KEY = 'helios.refresh_token'

export const tokenStore = {
  get access() {
    return localStorage.getItem(ACCESS_KEY)
  },
  get refresh() {
    return localStorage.getItem(REFRESH_KEY)
  },
  set(pair: TokenPair) {
    localStorage.setItem(ACCESS_KEY, pair.access_token)
    localStorage.setItem(REFRESH_KEY, pair.refresh_token)
  },
  clear() {
    localStorage.removeItem(ACCESS_KEY)
    localStorage.removeItem(REFRESH_KEY)
  },
}

export class ApiError extends Error {
  status: number
  detail: unknown
  constructor(status: number, detail: unknown, message: string) {
    super(message)
    this.status = status
    this.detail = detail
  }
}

interface RequestOptions extends Omit<RequestInit, 'body'> {
  body?: unknown
  /** Skip Authorization header (e.g. login). */
  auth?: boolean
  /** Internal: prevents infinite refresh recursion. */
  _retried?: boolean
}

async function refreshAccessToken(): Promise<boolean> {
  const refresh = tokenStore.refresh
  if (!refresh) return false
  const resp = await fetch(`${BASE_URL}/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: refresh }),
  })
  if (!resp.ok) {
    tokenStore.clear()
    return false
  }
  tokenStore.set((await resp.json()) as TokenPair)
  return true
}

export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { body, auth = true, _retried = false, headers, ...rest } = options

  const finalHeaders = new Headers(headers)
  if (body !== undefined) finalHeaders.set('Content-Type', 'application/json')
  if (auth && tokenStore.access) {
    finalHeaders.set('Authorization', `Bearer ${tokenStore.access}`)
  }

  const resp = await fetch(`${BASE_URL}${path}`, {
    ...rest,
    headers: finalHeaders,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })

  // Attempt a single transparent refresh on auth failure.
  if (resp.status === 401 && auth && !_retried) {
    const refreshed = await refreshAccessToken()
    if (refreshed) {
      return apiFetch<T>(path, { ...options, _retried: true })
    }
  }

  if (resp.status === 204) {
    return undefined as T
  }

  const isJson = resp.headers.get('content-type')?.includes('application/json')
  const payload = isJson ? await resp.json() : await resp.text()

  if (!resp.ok) {
    const detail =
      isJson && payload && typeof payload === 'object' && 'detail' in payload
        ? (payload as { detail: unknown }).detail
        : payload
    throw new ApiError(resp.status, detail, `Request failed (${resp.status})`)
  }

  return payload as T
}
