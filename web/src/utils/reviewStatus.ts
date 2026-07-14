export function reviewStatusColor(status: string): string {
  switch (status) {
    case 'pending':
    case 'editing':
      return 'yellow'
    case 'approved':
    case 'publishing':
      return 'blue'
    case 'published':
      return 'teal'
    case 'rejected':
    case 'expired':
      return 'gray'
    case 'failed':
      return 'red'
    default:
      return 'gray'
  }
}

export function reviewStatusLabel(status: string): string {
  const map: Record<string, string> = {
    pending: '待审核',
    editing: '编辑中',
    approved: '已批准',
    publishing: '发布中',
    published: '已发布',
    rejected: '已拒绝',
    failed: '失败',
    expired: '已过期',
  }
  return map[status] ?? status
}
