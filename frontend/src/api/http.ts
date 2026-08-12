/** The shared HTTP boundary: URL building, error shaping, and JSON requests. */

import { API_BASE_URL } from './endpoints'

/** A request that reached the backend and came back unusable. */
export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export const JSON_HEADERS = { 'Content-Type': 'application/json' }

export function apiUrl(path: string): string {
  return `${API_BASE_URL}${path}`
}

/** The backend's error detail when it sent one, else something naming the status. */
export async function errorMessage(response: Response): Promise<string> {
  const body = (await response.json().catch(() => null)) as { detail?: string } | null
  return body?.detail ?? `Request failed (${response.status})`
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(apiUrl(path), init)
  if (!response.ok) throw new ApiError(response.status, await errorMessage(response))
  return (await response.json()) as T
}
