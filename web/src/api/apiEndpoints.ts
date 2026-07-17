import { apiRequest } from './client'

export interface ApiEndpoint {
  id: number
  name: string
  token_prefix: string
  enabled: boolean
  expires_at: string | null
  last_access_at: string | null
  source_ids: number[]
  created_at: string | null
  updated_at: string | null
}

export interface ApiEndpointWithSecret extends ApiEndpoint {
  token: string
}

export async function listApiEndpoints(): Promise<{ items: ApiEndpoint[] }> {
  return apiRequest('/api/v1/api-endpoints')
}

export async function createApiEndpoint(body: {
  name: string
  enabled?: boolean
  expires_at?: string | null
  source_ids?: number[]
}): Promise<ApiEndpointWithSecret> {
  return apiRequest('/api/v1/api-endpoints', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export async function patchApiEndpoint(
  id: number,
  body: Partial<{ name: string; enabled: boolean; expires_at: string | null }>,
): Promise<ApiEndpoint> {
  return apiRequest(`/api/v1/api-endpoints/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

export async function rotateApiEndpointToken(id: number): Promise<ApiEndpointWithSecret> {
  return apiRequest(`/api/v1/api-endpoints/${id}/rotate-token`, {
    method: 'POST',
    body: JSON.stringify({}),
  })
}

export async function setApiEndpointSources(
  id: number,
  source_ids: number[],
): Promise<{ source_ids: number[] }> {
  return apiRequest(`/api/v1/api-endpoints/${id}/sources`, {
    method: 'PUT',
    body: JSON.stringify({ source_ids }),
  })
}

export async function deleteApiEndpoint(id: number): Promise<void> {
  await apiRequest(`/api/v1/api-endpoints/${id}`, { method: 'DELETE' })
}
