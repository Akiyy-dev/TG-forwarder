import type { Role } from '../api/types'

const WRITABLE = new Set(['pending', 'editing', 'failed', 'approved'])

export function canWriteReviews(role: Role | undefined): boolean {
  return role === 'reviewer' || role === 'super_admin'
}

export function canMutateTask(role: Role | undefined, status: string): boolean {
  return canWriteReviews(role) && WRITABLE.has(status)
}

export function canPublishTask(role: Role | undefined, status: string): boolean {
  return canWriteReviews(role) && ['pending', 'editing', 'approved', 'failed'].includes(status)
}

export function canRejectTask(role: Role | undefined, status: string): boolean {
  return canWriteReviews(role) && ['pending', 'editing', 'failed', 'approved'].includes(status)
}

export function canApproveTask(role: Role | undefined, status: string): boolean {
  return canWriteReviews(role) && ['pending', 'editing', 'failed'].includes(status)
}
