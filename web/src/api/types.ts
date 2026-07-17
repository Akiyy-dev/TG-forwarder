export type Role = 'viewer' | 'reviewer' | 'super_admin'
export type SourceBackend = 'telegram' | 'safew'

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
    telegram_receiver_running: boolean
    safew_receiver_running: boolean
    sender_running: boolean
    publisher_running: boolean
    bot_polling_enabled: boolean
    bot_available: boolean
    queue_size: number | null
    queue_size_available: boolean
    queue_size_source: 'process_memory' | 'redis_stream'
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
    source_backend: SourceBackend
    source_chat_id: number
    source_message_id: number
    error: string | null
    retry_count: number
  }>
  recent_reviews: Array<{
    id: number
    status: string
    source_backend: SourceBackend
    source_chat_id: number
    source_message_id: number
    source_title?: string | null
    updated_at: string | null
  }>
}

export interface PageMeta {
  page: number
  page_size: number
  total: number
  total_pages: number
}

export interface PageResult<T> {
  items: T[]
  meta: PageMeta
}

export interface ReviewTask {
  id: number
  status: string
  source_backend: SourceBackend
  source_chat_id: number
  source_message_id: number
  source_title?: string | null
  target_chat_id: number | null
  target_chat_ids?: number[] | null
  original_text: string
  processed_text: string
  final_text: string
  media_type: string
  media_count: number
  matched_rules: unknown[] | null
  detected_keywords: unknown[] | null
  decision_reason: string | null
  revision: number
  error_message: string | null
  created_at?: string | null
  updated_at?: string | null
  published_at?: string | null
}

export interface ContentRevision {
  revision_number: number
  source: string
  content: string
  created_by: number | null
  created_at: string | null
}

export interface ReviewActionItem {
  action: string
  old_status: string | null
  new_status: string | null
  user_id: number | null
  detail: Record<string, unknown> | null
  created_at: string | null
}

export interface ReviewDetail {
  task: ReviewTask
  revisions: ContentRevision[]
  actions: ReviewActionItem[]
}

export interface ReviewPreview {
  approximate: boolean
  disclaimer: string
  target_chat_id: number | null
  media_type: string
  media_count: number
  text: string
  text_length: number
  limit: number
  truncated: boolean
  uses_caption: boolean
  album_caption_note?: string | null
  split_plan?: unknown
  media_items: Array<{
    index: number
    media_type: string
    original_filename: string | null
    mime_type: string | null
    file_size: number | null
    available: boolean
    url: string | null
  }>
}
