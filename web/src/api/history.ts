import { apiRequest } from './client'
import type { PageResult, SourceBackend } from './types'

export interface HistoryItem {
  id: number
  source_chat_id: number
  source_message_id: number
  source_backend: SourceBackend
  source_title: string | null
  status: string
  text: string | null
  media_type: string
  publish_mode: string | null
  target_chat_id: number | null
  target_chat_ids: number[]
  target_message_ids: number[]
  api_delivery_count: number
  skip_reason: string | null
  error_message: string | null
  retry_count: number
  received_at: string | null
  processed_at: string | null
  published_at: string | null
  updated_at: string | null
}

export async function listHistory(params: {
  page?: number
  page_size?: number
  source_id?: number
  status?: string
} = {}): Promise<PageResult<HistoryItem>> {
  const qs = new URLSearchParams()
  if (params.page) qs.set('page', String(params.page))
  if (params.page_size) qs.set('page_size', String(params.page_size))
  if (params.source_id) qs.set('source_id', String(params.source_id))
  if (params.status) qs.set('status', params.status)
  const query = qs.toString()
  return apiRequest(`/api/v1/history${query ? `?${query}` : ''}`)
}
