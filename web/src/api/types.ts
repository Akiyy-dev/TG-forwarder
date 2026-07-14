export type Role = 'viewer' | 'reviewer' | 'super_admin'

export interface User {
  id: number
  username: string
  role: Role
  is_active: boolean
  created_at?: string | null
  last_login_at?: string | null
}

export interface Envelope<T> {
  ok: boolean
  data: T
  meta?: Record<string, unknown>
}

export interface ApiErrorBody {
  code: string
  message: string
  details?: Record<string, unknown>
  request_id?: string
}

export interface DashboardSummary {
  service: {
    web_enabled: boolean
    started_at: string
    publishing_paused: boolean
    listener_running: boolean
    bot_available: boolean
    queue_size: number
  }
  counts: {
    pending_review: number
    source_channels: number
    target_channels: number
    rules: number
    today_received: number
    today_published: number
    today_failed: number
    today_rejected: number
    by_status: Record<string, number>
  }
  recent_errors: Array<{
    source_chat_id: number
    source_message_id: number
    error: string | null
    retry_count: number
  }>
  recent_reviews: Array<{
    id: number
    status: string
    source_chat_id: number
    source_message_id: number
    updated_at: string | null
  }>
}
