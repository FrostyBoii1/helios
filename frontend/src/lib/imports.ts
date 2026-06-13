// Import staging/review API calls (thin wrappers over apiFetch).

import { apiFetch } from '@/lib/api'
import type {
  BulkApproveResult,
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
} from '@/types/imports'

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

export function editRow(batchId: number, rowId: number, edit: ImportRowEdit): Promise<ImportRow> {
  return apiFetch<ImportRow>(`/imports/${batchId}/rows/${rowId}`, { method: 'PATCH', body: edit })
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

export type { RowAction, ImportRowReviewStatus }
