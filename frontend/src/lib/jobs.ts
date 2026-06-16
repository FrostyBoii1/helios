// Job API calls (thin wrappers over apiFetch).

import { apiFetch } from '@/lib/api'
import type { Job, JobInput, JobListResponse, JobStatus } from '@/types'

export interface ListJobsParams {
  q?: string
  customer_id?: number
  status?: JobStatus
  /** Filter by operational label key (single-label). */
  label?: string
  install_date_from?: string
  install_date_to?: string
  unscheduled?: boolean
  limit?: number
  offset?: number
}

export function listJobs(params: ListJobsParams = {}): Promise<JobListResponse> {
  const search = new URLSearchParams()
  if (params.q) search.set('q', params.q)
  if (params.customer_id != null) search.set('customer_id', String(params.customer_id))
  if (params.status) search.set('status', params.status)
  if (params.label) search.set('label', params.label)
  if (params.install_date_from) search.set('install_date_from', params.install_date_from)
  if (params.install_date_to) search.set('install_date_to', params.install_date_to)
  if (params.unscheduled) search.set('unscheduled', 'true')
  if (params.limit != null) search.set('limit', String(params.limit))
  if (params.offset != null) search.set('offset', String(params.offset))
  const qs = search.toString()
  return apiFetch<JobListResponse>(`/jobs${qs ? `?${qs}` : ''}`)
}

export function getJob(id: number): Promise<Job> {
  return apiFetch<Job>(`/jobs/${id}`)
}

export function createJob(customerId: number, input: JobInput): Promise<Job> {
  return apiFetch<Job>('/jobs', { method: 'POST', body: { customer_id: customerId, ...input } })
}

export function updateJob(id: number, input: JobInput): Promise<Job> {
  return apiFetch<Job>(`/jobs/${id}`, { method: 'PATCH', body: input })
}

export function changeJobStatus(id: number, status: JobStatus): Promise<Job> {
  return apiFetch<Job>(`/jobs/${id}/status`, { method: 'POST', body: { status } })
}

export function deleteJob(id: number): Promise<void> {
  return apiFetch<void>(`/jobs/${id}`, { method: 'DELETE' })
}
