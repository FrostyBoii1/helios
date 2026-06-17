// Import staging/review API calls (thin wrappers over apiFetch).

import { apiFetch } from '@/lib/api'
import type {
  BulkApproveResult,
  CustomerGroupMutationResult,
  CustomerGroupRead,
  CustomerResolutionRequest,
  FieldRegistry,
  ImportBatch,
  ImportBatchList,
  ImportBatchSummary,
  ImportCommitPreview,
  ImportCommitResult,
  ImportIssue,
  ImportRow,
  ImportRowEdit,
  ImportRowList,
  ImportRowReviewStatus,
  ListRowsParams,
  MatchCandidate,
  ReverseCheck,
  ReverseResult,
} from '@/types/imports'

export function getFieldRegistry(): Promise<FieldRegistry> {
  return apiFetch<FieldRegistry>('/imports/field-registry')
}

export function listBatches(): Promise<ImportBatchList> {
  return apiFetch<ImportBatchList>('/imports')
}

export function getBatch(id: number): Promise<ImportBatch> {
  return apiFetch<ImportBatch>(`/imports/${id}`)
}

export function getBatchSummary(id: number): Promise<ImportBatchSummary> {
  return apiFetch<ImportBatchSummary>(`/imports/${id}/summary`)
}

export function listRows(batchId: number, params: ListRowsParams = {}): Promise<ImportRowList> {
  const search = new URLSearchParams()
  if (params.row_class) search.set('row_class', params.row_class)
  if (params.review_status) search.set('review_status', params.review_status)
  if (params.severity) search.set('severity', params.severity)
  if (params.unresolved_only) search.set('unresolved_only', 'true')
  if (params.q) search.set('q', params.q)
  if (params.limit != null) search.set('limit', String(params.limit))
  if (params.offset != null) search.set('offset', String(params.offset))
  const qs = search.toString()
  return apiFetch<ImportRowList>(`/imports/${batchId}/rows${qs ? `?${qs}` : ''}`)
}

export function getRow(batchId: number, rowId: number): Promise<ImportRow> {
  return apiFetch<ImportRow>(`/imports/${batchId}/rows/${rowId}`)
}

// Section B1: advisory same-customer candidates for a row (read-only).
export function getRowMatchCandidates(
  batchId: number,
  rowId: number,
): Promise<MatchCandidate[]> {
  return apiFetch<MatchCandidate[]>(`/imports/${batchId}/rows/${rowId}/match-candidates`)
}

export function editRow(batchId: number, rowId: number, edit: ImportRowEdit): Promise<ImportRow> {
  return apiFetch<ImportRow>(`/imports/${batchId}/rows/${rowId}`, { method: 'PATCH', body: edit })
}

// Section B2-3: set or clear the row's manual same-customer resolution
// (mode existing/new/clear). Returns the updated row.
export function resolveRowCustomer(
  batchId: number,
  rowId: number,
  payload: CustomerResolutionRequest,
): Promise<ImportRow> {
  return apiFetch<ImportRow>(`/imports/${batchId}/rows/${rowId}/resolve-customer`, {
    method: 'POST',
    body: payload,
  })
}

// ---- Section B3-4: pending-row groups (admin-only) ----
export function getCustomerGroup(batchId: number, groupId: number): Promise<CustomerGroupRead> {
  return apiFetch<CustomerGroupRead>(`/imports/${batchId}/customer-groups/${groupId}`)
}

export function createCustomerGroup(
  batchId: number,
  primaryRowId: number,
  memberRowIds: number[],
  reason?: string | null,
): Promise<CustomerGroupRead> {
  return apiFetch<CustomerGroupRead>(`/imports/${batchId}/customer-groups`, {
    method: 'POST',
    body: { primary_row_id: primaryRowId, member_row_ids: memberRowIds, reason: reason ?? null },
  })
}

export function addGroupRow(batchId: number, groupId: number, rowId: number): Promise<CustomerGroupRead> {
  return apiFetch<CustomerGroupRead>(`/imports/${batchId}/customer-groups/${groupId}/rows`, {
    method: 'POST',
    body: { row_id: rowId },
  })
}

export function removeGroupRow(
  batchId: number,
  groupId: number,
  rowId: number,
): Promise<CustomerGroupMutationResult> {
  return apiFetch<CustomerGroupMutationResult>(
    `/imports/${batchId}/customer-groups/${groupId}/rows/${rowId}`,
    { method: 'DELETE' },
  )
}

export function setGroupPrimary(
  batchId: number,
  groupId: number,
  primaryRowId: number,
): Promise<CustomerGroupRead> {
  return apiFetch<CustomerGroupRead>(`/imports/${batchId}/customer-groups/${groupId}`, {
    method: 'PATCH',
    body: { primary_row_id: primaryRowId },
  })
}

export function dissolveCustomerGroup(
  batchId: number,
  groupId: number,
): Promise<CustomerGroupMutationResult> {
  return apiFetch<CustomerGroupMutationResult>(`/imports/${batchId}/customer-groups/${groupId}`, {
    method: 'DELETE',
  })
}

type RowAction = 'approve' | 'reject' | 'skip' | 'reopen'

export function rowAction(
  batchId: number,
  rowId: number,
  action: RowAction,
  notes?: string,
): Promise<ImportRow> {
  // approve/reopen take no body; reject/skip accept an optional note.
  const body = action === 'reject' || action === 'skip' ? { notes: notes ?? null } : undefined
  return apiFetch<ImportRow>(`/imports/${batchId}/rows/${rowId}/${action}`, {
    method: 'POST',
    body,
  })
}

export function resolveIssue(
  batchId: number,
  issueId: number,
  resolutionNote?: string,
): Promise<ImportIssue> {
  return apiFetch<ImportIssue>(`/imports/${batchId}/issues/${issueId}`, {
    method: 'PATCH',
    body: { resolution_note: resolutionNote ?? null },
  })
}

export function bulkApproveClean(batchId: number): Promise<BulkApproveResult> {
  return apiFetch<BulkApproveResult>(`/imports/${batchId}/bulk-approve-clean`, { method: 'POST' })
}

export function uploadBatch(file: File): Promise<ImportBatch> {
  const form = new FormData()
  form.append('file', file)
  return apiFetch<ImportBatch>('/imports', { method: 'POST', body: form })
}

export function getCommitPreview(batchId: number, sampleLimit = 25): Promise<ImportCommitPreview> {
  return apiFetch<ImportCommitPreview>(
    `/imports/${batchId}/commit-preview?sample_limit=${sampleLimit}`,
  )
}

// Commit the next eligible rows (backend caps the count). No row_ids in C2 —
// the backend deterministically commits the next batch in chronological order.
export function commitBatch(batchId: number): Promise<ImportCommitResult> {
  return apiFetch<ImportCommitResult>(`/imports/${batchId}/commit`, { method: 'POST', body: {} })
}

// Read-only: can this committed row be reversed (and why not)?
export function getReverseCheck(batchId: number, rowId: number): Promise<ReverseCheck> {
  return apiFetch<ReverseCheck>(`/imports/${batchId}/rows/${rowId}/reverse-check`)
}

// Per-row reverse. Returns 200 with status 'reversed' | 'blocked' (not a 409).
export function reverseRow(batchId: number, rowId: number): Promise<ReverseResult> {
  return apiFetch<ReverseResult>(`/imports/${batchId}/rows/${rowId}/reverse`, { method: 'POST', body: {} })
}

export type { RowAction, ImportRowReviewStatus }
