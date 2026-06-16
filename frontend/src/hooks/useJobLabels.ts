// TanStack Query hooks for job labels.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  assignJobLabel,
  listJobLabels,
  listLabelDefinitions,
  removeJobLabel,
  setJobApproval,
} from '@/lib/jobLabels'
import type { JobApprovalState } from '@/types'

const keys = {
  definitions: ['job-labels', 'definitions'] as const,
  forJob: (jobId: number) => ['job-labels', 'job', jobId] as const,
}

export function useLabelDefinitions() {
  return useQuery({
    queryKey: keys.definitions,
    queryFn: listLabelDefinitions,
    staleTime: 5 * 60_000, // the catalogue rarely changes
  })
}

export function useJobLabels(jobId: number) {
  return useQuery({
    queryKey: keys.forJob(jobId),
    queryFn: () => listJobLabels(jobId),
    enabled: Number.isFinite(jobId) && jobId > 0,
  })
}

export function useAssignJobLabel(jobId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (key: string) => assignJobLabel(jobId, key),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.forJob(jobId) })
      // The Jobs list rows embed label chips. This invalidation is LOAD-BEARING:
      // the global query default is staleTime 30s (lib/queryClient.ts), so merely
      // navigating back to the Jobs list within 30s serves cached rows and does NOT
      // refetch — the chip change would be invisible until the window elapses.
      // Invalidating ['jobs'] forces a refetch of every jobs list/detail query
      // (global Jobs page + customer-embedded list both key on ['jobs', ...]).
      void qc.invalidateQueries({ queryKey: ['jobs'] })
    },
  })
}

export function useRemoveJobLabel(jobId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (key: string) => removeJobLabel(jobId, key),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.forJob(jobId) })
      // Same as add, and equally load-bearing (30s staleTime — see useAssignJobLabel):
      // a removed chip must disappear from the Jobs list rows immediately, not after
      // the cache window elapses.
      void qc.invalidateQueries({ queryKey: ['jobs'] })
    },
  })
}

export function useSetJobApproval(jobId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: { state: JobApprovalState; pending_date: string | null }) =>
      setJobApproval(jobId, input.state, input.pending_date),
    onSuccess: () => {
      // labels drive the approval chip; the job carries details.approval.pending_date.
      void qc.invalidateQueries({ queryKey: keys.forJob(jobId) })
      // Approval changes an approval label chip — refresh job detail AND the Jobs
      // list rows (which show the chip).
      void qc.invalidateQueries({ queryKey: ['jobs'] })
    },
  })
}
