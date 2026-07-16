import type { SourceBackend } from '../api/types'

export function sourceBackendLabel(backend?: SourceBackend | null): string {
  if (backend === 'safew') return 'SafeW'
  if (backend === 'telegram') return 'Telegram'
  return '未知来源'
}
