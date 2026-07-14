import { apiRequest } from './client'
import type { PageResult } from './types'

export interface SourceChannel {
  id: number
  chat_id: number
  username: string | null
  title: string | null
  enabled: boolean
  publish_mode: string
  target_channel_id: number | null
  processing_profile: string
  created_at?: string | null
  updated_at?: string | null
}

export interface TargetChannel {
  id: number
  chat_id: number
  username: string | null
  title: string | null
  enabled: boolean
  default_footer: string | null
  permission_status: string
  permission_detail: Record<string, unknown> | null
  last_permission_check_at: string | null
  created_at?: string | null
  updated_at?: string | null
}

export async function listChannels(params: {
  page?: number
  page_size?: number
  enabled?: boolean
  publish_mode?: string
  q?: string
} = {}): Promise<PageResult<SourceChannel>> {
  const qs = new URLSearchParams()
  if (params.page) qs.set('page', String(params.page))
  if (params.page_size) qs.set('page_size', String(params.page_size))
  if (params.enabled != null) qs.set('enabled', String(params.enabled))
  if (params.publish_mode) qs.set('publish_mode', params.publish_mode)
  if (params.q) qs.set('q', params.q)
  const query = qs.toString()
  return apiRequest(`/api/v1/channels${query ? `?${query}` : ''}`)
}

export async function createChannel(body: {
  chat_id: number
  title?: string
  username?: string
  publish_mode?: string
  target_channel_id?: number | null
  enabled?: boolean
}): Promise<SourceChannel> {
  return apiRequest('/api/v1/channels', { method: 'POST', body: JSON.stringify(body) })
}

export async function patchChannel(
  id: number,
  body: Partial<{
    title: string
    enabled: boolean
    publish_mode: string
    target_channel_id: number | null
  }>,
): Promise<SourceChannel> {
  return apiRequest(`/api/v1/channels/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

export async function deleteChannel(id: number): Promise<void> {
  await apiRequest(`/api/v1/channels/${id}`, { method: 'DELETE' })
}

export async function listTargets(): Promise<{ items: TargetChannel[] }> {
  return apiRequest('/api/v1/targets')
}

export async function createTarget(body: {
  chat_id: number
  title?: string
  username?: string
  enabled?: boolean
}): Promise<TargetChannel> {
  return apiRequest('/api/v1/targets', { method: 'POST', body: JSON.stringify(body) })
}

export async function patchTarget(
  id: number,
  body: Partial<{ title: string; enabled: boolean; default_footer: string | null }>,
): Promise<TargetChannel> {
  return apiRequest(`/api/v1/targets/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

export async function checkTargetPermissions(id: number): Promise<Record<string, unknown>> {
  return apiRequest(`/api/v1/targets/${id}/check-permissions`, { method: 'POST' })
}

export async function sendTargetTestMessage(
  id: number,
  text: string,
): Promise<Record<string, unknown>> {
  return apiRequest(`/api/v1/targets/${id}/test-message`, {
    method: 'POST',
    body: JSON.stringify({ text }),
  })
}
