import { apiRequest } from './client'
import type { PageResult } from './types'

export interface KeywordRule {
  id: number
  name: string
  description: string | null
  enabled: boolean
  priority: number
  rule_type: string
  match_type: string
  pattern: string
  replacement: string | null
  case_sensitive: boolean
  whole_word: boolean
  use_regex: boolean
  source_channel_ids: number[] | null
  target_channel_ids: number[] | null
  message_types: string[] | null
  action: string
  stop_processing: boolean
  group_id: number | null
  hit_count: number
  last_hit_at: string | null
  created_by: number | null
  created_at?: string | null
  updated_at?: string | null
}

export interface RuleWrite {
  name: string
  pattern: string
  description?: string | null
  enabled?: boolean
  priority?: number
  rule_type?: string
  match_type?: string
  replacement?: string | null
  case_sensitive?: boolean
  whole_word?: boolean
  use_regex?: boolean
  action?: string
  stop_processing?: boolean
  group_id?: number | null
}

export async function listRules(params: {
  page?: number
  page_size?: number
  enabled?: boolean
  q?: string
} = {}): Promise<PageResult<KeywordRule>> {
  const qs = new URLSearchParams()
  if (params.page) qs.set('page', String(params.page))
  if (params.page_size) qs.set('page_size', String(params.page_size))
  if (params.enabled != null) qs.set('enabled', String(params.enabled))
  if (params.q) qs.set('q', params.q)
  const query = qs.toString()
  return apiRequest(`/api/v1/rules${query ? `?${query}` : ''}`)
}

export async function createRule(body: RuleWrite): Promise<KeywordRule> {
  return apiRequest('/api/v1/rules', { method: 'POST', body: JSON.stringify(body) })
}

export async function patchRule(id: number, body: Partial<RuleWrite>): Promise<KeywordRule> {
  return apiRequest(`/api/v1/rules/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

export async function deleteRule(id: number): Promise<void> {
  await apiRequest(`/api/v1/rules/${id}`, { method: 'DELETE' })
}

export async function duplicateRule(id: number): Promise<KeywordRule> {
  return apiRequest(`/api/v1/rules/${id}/duplicate`, { method: 'POST' })
}

export async function testRule(
  id: number | null,
  sample_text: string,
  rule?: RuleWrite,
): Promise<{ matched: boolean; hits: unknown[]; final_text: string }> {
  if (id != null) {
    return apiRequest(`/api/v1/rules/${id}/test`, {
      method: 'POST',
      body: JSON.stringify({ sample_text }),
    })
  }
  return apiRequest('/api/v1/rules/test', {
    method: 'POST',
    body: JSON.stringify({ sample_text, rule }),
  })
}
