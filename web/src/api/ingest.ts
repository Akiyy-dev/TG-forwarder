import { apiRequest } from './client'

export interface IngestSource {
  id: number
  name: string
  source_id: number
  source_chat_id: number
  token_prefix: string
  enabled: boolean
  expires_at: string | null
  last_access_at: string | null
  created_at: string | null
}

export interface IngestSourceWithSecret extends IngestSource {
  token: string
}

export interface IngestSourceInput {
  name: string
  enabled?: boolean
  expires_at?: string | null
}

export async function listIngestSources(): Promise<{ items: IngestSource[] }> {
  return apiRequest('/api/v1/ingest-sources')
}

export async function createIngestSource(body: IngestSourceInput): Promise<IngestSourceWithSecret> {
  return apiRequest('/api/v1/ingest-sources', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export async function patchIngestSource(
  id: number,
  body: Partial<IngestSourceInput>,
): Promise<IngestSource> {
  return apiRequest(`/api/v1/ingest-sources/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

export async function rotateIngestSourceToken(id: number): Promise<IngestSourceWithSecret> {
  return apiRequest(`/api/v1/ingest-sources/${id}/rotate-token`, { method: 'POST' })
}

export async function revokeIngestSource(id: number): Promise<void> {
  await apiRequest(`/api/v1/ingest-sources/${id}`, { method: 'DELETE' })
}
