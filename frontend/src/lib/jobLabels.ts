// Job label API calls (thin wrappers over apiFetch).

import { apiFetch } from '@/lib/api'
import type {
  JobApprovalRead,
  JobApprovalState,
  JobLabelAssignment,
  JobLabelDefinition,
} from '@/types'

export function listLabelDefinitions(): Promise<JobLabelDefinition[]> {
  return apiFetch<JobLabelDefinition[]>('/job-labels')
}

export function listJobLabels(jobId: number): Promise<JobLabelAssignment[]> {
  return apiFetch<JobLabelAssignment[]>(`/jobs/${jobId}/labels`)
}

export function assignJobLabel(jobId: number, key: string): Promise<JobLabelAssignment> {
  return apiFetch<JobLabelAssignment>(`/jobs/${jobId}/labels`, {
    method: 'POST',
    body: { key },
  })
}

export function removeJobLabel(jobId: number, key: string): Promise<void> {
  return apiFetch<void>(`/jobs/${jobId}/labels/${encodeURIComponent(key)}`, {
    method: 'DELETE',
  })
}

export function setJobApproval(
  jobId: number,
  state: JobApprovalState,
  pendingDate: string | null,
): Promise<JobApprovalRead> {
  return apiFetch<JobApprovalRead>(`/jobs/${jobId}/approval`, {
    method: 'PUT',
    body: { state, pending_date: pendingDate },
  })
}
