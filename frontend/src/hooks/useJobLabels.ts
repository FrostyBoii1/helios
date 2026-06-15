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
    },
  })
}

export function useRemoveJobLabel(jobId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (key: string) => removeJobLabel(jobId, key),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.forJob(jobId) })
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
      void qc.invalidateQueries({ queryKey: ['jobs', 'detail', jobId] })
    },
  })
}
