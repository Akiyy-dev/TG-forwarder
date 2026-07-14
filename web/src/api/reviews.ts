import { apiRequest } from './client'
import type { PageResult, ReviewDetail, ReviewPreview, ReviewTask } from './types'

export interface ReviewListParams {
  page?: number
  page_size?: number
  status?: string
  source_chat_id?: number
  q?: string
}

export async function listReviews(params: ReviewListParams = {}): Promise<PageResult<ReviewTask>> {
  const qs = new URLSearchParams()
  if (params.page) qs.set('page', String(params.page))
  if (params.page_size) qs.set('page_size', String(params.page_size))
  if (params.status) qs.set('status', params.status)
  if (params.source_chat_id != null) qs.set('source_chat_id', String(params.source_chat_id))
  if (params.q) qs.set('q', params.q)
  const query = qs.toString()
  return apiRequest(`/api/v1/reviews${query ? `?${query}` : ''}`)
}

export async function getReview(taskId: number): Promise<ReviewDetail> {
  return apiRequest(`/api/v1/reviews/${taskId}`)
}

export async function editReview(
  taskId: number,
  content: string,
  expected_revision: number,
): Promise<ReviewTask> {
  return apiRequest(`/api/v1/reviews/${taskId}/edit`, {
    method: 'POST',
    body: JSON.stringify({ content, expected_revision }),
  })
}

export async function approveReview(
  taskId: number,
  expected_revision: number,
  reason?: string,
): Promise<ReviewTask> {
  return apiRequest(`/api/v1/reviews/${taskId}/approve`, {
    method: 'POST',
    body: JSON.stringify({ expected_revision, reason }),
  })
}

export async function rejectReview(
  taskId: number,
  expected_revision: number,
  reason?: string,
): Promise<ReviewTask> {
  return apiRequest(`/api/v1/reviews/${taskId}/reject`, {
    method: 'POST',
    body: JSON.stringify({ expected_revision, reason }),
  })
}

export async function publishReview(
  taskId: number,
  expected_revision: number,
  reason?: string,
): Promise<Record<string, unknown>> {
  return apiRequest(`/api/v1/reviews/${taskId}/publish`, {
    method: 'POST',
    body: JSON.stringify({ expected_revision, reason }),
  })
}

export async function restoreReview(
  taskId: number,
  expected_revision: number,
  revision_number: number,
): Promise<ReviewTask> {
  return apiRequest(`/api/v1/reviews/${taskId}/restore`, {
    method: 'POST',
    body: JSON.stringify({ expected_revision, revision_number }),
  })
}

export async function reapplyRules(
  taskId: number,
  body: {
    expected_revision: number
    source?: 'original' | 'current'
    confirm_reject?: boolean
  },
): Promise<{ preview: Record<string, unknown>; task?: ReviewTask }> {
  return apiRequest(`/api/v1/reviews/${taskId}/reapply-rules`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export async function batchReject(
  ids: number[],
  expected_revisions?: Record<string, number>,
  reason?: string,
): Promise<{ results: Array<{ id: number; ok: boolean; error?: string }> }> {
  return apiRequest('/api/v1/reviews/batch/reject', {
    method: 'POST',
    body: JSON.stringify({ ids, expected_revisions, reason }),
  })
}

export async function batchPublish(
  ids: number[],
  expected_revisions?: Record<string, number>,
  reason?: string,
): Promise<{ results: Array<{ id: number; ok: boolean; error?: string }> }> {
  return apiRequest('/api/v1/reviews/batch/publish', {
    method: 'POST',
    body: JSON.stringify({ ids, expected_revisions, reason }),
  })
}

export async function fetchReviewPreview(taskId: number): Promise<ReviewPreview> {
  return apiRequest(`/api/v1/reviews/${taskId}/preview`)
}
