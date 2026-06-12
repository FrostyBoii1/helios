// TanStack Query hooks for jobs.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  changeJobStatus,
  createJob,
  deleteJob,
  getJob,
  listJobs,
  updateJob,
  type ListJobsParams,
} from '@/lib/jobs'
import type { JobInput, JobStatus } from '@/types'

const keys = {
  all: ['jobs'] as const,
  list: (params: ListJobsParams) => ['jobs', 'list', params] as const,
  detail: (id: number) => ['jobs', 'detail', id] as const,
}

export function useJobs(params: ListJobsParams) {
  return useQuery({
    queryKey: keys.list(params),
    queryFn: () => listJobs(params),
  })
}

export function useJob(id: number) {
  return useQuery({
    queryKey: keys.detail(id),
    queryFn: () => getJob(id),
    enabled: Number.isFinite(id) && id > 0,
  })
}

export function useCreateJob() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ customerId, input }: { customerId: number; input: JobInput }) =>
      createJob(customerId, input),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.all })
    },
  })
}

export function useUpdateJob(id: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: JobInput) => updateJob(id, input),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.all })
      void qc.invalidateQueries({ queryKey: keys.detail(id) })
    },
  })
}

export function useChangeJobStatus(id: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (status: JobStatus) => changeJobStatus(id, status),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.all })
      void qc.invalidateQueries({ queryKey: keys.detail(id) })
    },
  })
}

export function useDeleteJob() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => deleteJob(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.all })
    },
  })
}
