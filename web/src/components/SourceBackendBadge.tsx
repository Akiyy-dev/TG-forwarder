import { Badge } from '@mantine/core'
import type { SourceBackend } from '../api/types'
import { sourceBackendLabel } from '../utils/sourceBackend'

interface SourceBackendBadgeProps {
  backend?: SourceBackend | null
  size?: 'xs' | 'sm' | 'md' | 'lg' | 'xl'
}

export function SourceBackendBadge({ backend, size = 'sm' }: SourceBackendBadgeProps) {
  const isSafeW = backend === 'safew'

  return (
    <Badge color={isSafeW ? 'violet' : backend === 'telegram' ? 'blue' : 'gray'} variant="light" size={size}>
      {sourceBackendLabel(backend)}
    </Badge>
  )
}
