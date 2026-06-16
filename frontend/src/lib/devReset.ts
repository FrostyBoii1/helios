// Dev/test-only reset API calls (thin wrappers over apiFetch).
// System-admin only; the backend also refuses these in production and requires an
// exact typed confirmation phrase.

import { apiFetch } from '@/lib/api'

export interface ResetCounts {
  imports: Record<string, number>
  live_crm: Record<string, number>
}

export interface ResetResult {
  action: string
  deleted: Record<string, number>
}

export function getResetCounts(): Promise<ResetCounts> {
  return apiFetch<ResetCounts>('/dev/reset/counts')
}

export function clearImports(confirm: string): Promise<ResetResult> {
  return apiFetch<ResetResult>('/dev/reset/imports', { method: 'POST', body: { confirm } })
}

export function clearLiveCrm(confirm: string): Promise<ResetResult> {
  return apiFetch<ResetResult>('/dev/reset/live-crm', { method: 'POST', body: { confirm } })
}
