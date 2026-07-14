import { apiRequest } from './client'
import type { DashboardSummary } from './types'

export async function fetchDashboard(): Promise<DashboardSummary> {
  return apiRequest<DashboardSummary>('/api/v1/dashboard')
}
