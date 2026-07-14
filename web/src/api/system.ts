import { apiRequest } from './client'
import type { PageResult } from './types'

export async function fetchSystemStatus(): Promise<{
  started_at: string
  publishing_paused: boolean
  queue_size: number
  last_error: string | null
  listener_running: boolean
  bot_available: boolean
  message_stats: Record<string, number>
}> {
  return apiRequest('/api/v1/system/status')
}

export async function pausePublishing(): Promise<{ publishing_paused: boolean }> {
  return apiRequest('/api/v1/system/pause', { method: 'POST' })
}

export async function resumePublishing(): Promise<{
  publishing_paused: boolean
  requeued: number
}> {
  return apiRequest('/api/v1/system/resume', { method: 'POST' })
}

export async function recoverPending(): Promise<{ requeued: number }> {
  return apiRequest('/api/v1/system/recover', { method: 'POST' })
}

export async function listReviewActionLogs(
  page = 1,
  page_size = 20,
): Promise<PageResult<Record<string, unknown>>> {
  return apiRequest(`/api/v1/logs/review-actions?page=${page}&page_size=${page_size}`)
}

export async function listProcessingLogs(
  page = 1,
  page_size = 20,
): Promise<PageResult<Record<string, unknown>>> {
  return apiRequest(`/api/v1/logs/processing?page=${page}&page_size=${page_size}`)
}

export async function listRuleExecutionLogs(
  page = 1,
  page_size = 20,
): Promise<PageResult<Record<string, unknown>>> {
  return apiRequest(`/api/v1/logs/rule-executions?page=${page}&page_size=${page_size}`)
}
