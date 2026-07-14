import { apiRequest } from './client'
import type { User } from './types'

export async function login(username: string, password: string): Promise<{ user: User }> {
  return apiRequest('/api/v1/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  })
}

export async function logout(): Promise<void> {
  await apiRequest<{ logged_out: boolean }>('/api/v1/auth/logout', { method: 'POST' })
}

export async function fetchMe(): Promise<User> {
  return apiRequest<User>('/api/v1/auth/me')
}
