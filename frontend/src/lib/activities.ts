// Activity timeline API calls (read-only).

import { apiFetch } from '@/lib/api'
import type { ActivityListResponse } from '@/types'

export interface ListActivitiesParams {
  customer_id?: number
  job_id?: number
  limit?: number
  offset?: number
}

export function listActivities(params: ListActivitiesParams): Promise<ActivityListResponse> {
  const search = new URLSearchParams()
  if (params.customer_id != null) search.set('customer_id', String(params.customer_id))
  if (params.job_id != null) search.set('job_id', String(params.job_id))
  if (params.limit != null) search.set('limit', String(params.limit))
  if (params.offset != null) search.set('offset', String(params.offset))
  return apiFetch<ActivityListResponse>(`/activities?${search.toString()}`)
}
