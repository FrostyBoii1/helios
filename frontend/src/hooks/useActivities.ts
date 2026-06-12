// TanStack Query hook for the activity timeline.

import { useQuery } from '@tanstack/react-query'
import { listActivities, type ListActivitiesParams } from '@/lib/activities'

export function useActivities(params: ListActivitiesParams) {
  const enabled = params.customer_id != null || params.job_id != null
  return useQuery({
    queryKey: ['activities', params],
    queryFn: () => listActivities(params),
    enabled,
  })
}
