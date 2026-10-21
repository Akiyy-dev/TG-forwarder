import type { SourceBackend } from '../api/types'

export function sourceBackendLabel(backend?: SourceBackend | null): string {
  if (backend === 'safew') return 'SafeW'
  if (backend === 'telegram') return 'Telegram'
  if (backend === 'api') return 'API 接入'
  return '未知来源'
}
