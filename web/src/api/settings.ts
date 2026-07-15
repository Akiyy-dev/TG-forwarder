import { apiRequest } from './client'

export interface SettingField {
  key: string
  value: unknown
  apply: string
  secret: boolean
  readonly: boolean
}

export interface SettingsPayload {
  groups: Record<string, SettingField[]>
  values: Record<string, unknown>
  schema?: Record<string, { apply?: string; group?: string; secret?: boolean }>
}

export async function getSettings(): Promise<SettingsPayload> {
  return apiRequest('/api/v1/settings')
}

export async function putSettings(
  values: Record<string, unknown>,
): Promise<{ apply: string; fields: string[]; values: Record<string, unknown> }> {
  return apiRequest('/api/v1/settings', {
    method: 'PUT',
    body: JSON.stringify({ values }),
  })
}
