// TanStack Query hooks for import staging/review.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  bulkApproveClean,
  commitBatch,
  editRow,
  getBatch,
  getBatchSummary,
  getCommitPreview,
  getReverseCheck,
  getRow,
  listBatches,
  listRows,
  resolveIssue,
  reverseRow,
  rowAction,
  uploadBatch,
  type RowAction,
} from '@/lib/imports'
import type { ImportRowEdit, ListRowsParams } from '@/types/imports'

const keys = {
  all: ['imports'] as const,
  batches: ['imports', 'batches'] as const,
  batch: (id: number) => ['imports', 'batch', id] as const,
  summary: (id: number) => ['imports', 'summary', id] as const,
  rows: (id: number, params: ListRowsParams) => ['imports', 'rows', id, params] as const,
  row: (batchId: number, rowId: number) => ['imports', 'row', batchId, rowId] as const,
  commitPreview: (id: number) => ['imports', 'commit-preview', id] as const,
  reverseCheck: (batchId: number, rowId: number) =>
    ['imports', 'reverse-check', batchId, rowId] as const,
}

export function useImportBatches() {
  return useQuery({ queryKey: keys.batches, queryFn: listBatches })
}

export function useImportBatch(id: number) {
  return useQuery({
    queryKey: keys.batch(id),
    queryFn: () => getBatch(id),
    enabled: Number.isFinite(id) && id > 0,
  })
}

export function useImportSummary(id: number) {
  return useQuery({
    queryKey: keys.summary(id),
    queryFn: () => getBatchSummary(id),
    enabled: Number.isFinite(id) && id > 0,
  })
}

export function useImportRows(id: number, params: ListRowsParams) {
  return useQuery({
    queryKey: keys.rows(id, params),
    queryFn: () => listRows(id, params),
    enabled: Number.isFinite(id) && id > 0,
  })
}

export function useImportRow(batchId: number, rowId: number | null) {
  return useQuery({
    queryKey: keys.row(batchId, rowId ?? 0),
    queryFn: () => getRow(batchId, rowId as number),
    enabled: Number.isFinite(batchId) && batchId > 0 && rowId != null && rowId > 0,
  })
}

export function useImportCommitPreview(batchId: number, enabled = true) {
  return useQuery({
    queryKey: keys.commitPreview(batchId),
    queryFn: () => getCommitPreview(batchId),
    enabled: enabled && Number.isFinite(batchId) && batchId > 0,
  })
}

export function useReverseCheck(batchId: number, rowId: number | null, enabled = true) {
  return useQuery({
    queryKey: keys.reverseCheck(batchId, rowId ?? 0),
    queryFn: () => getReverseCheck(batchId, rowId as number),
    enabled: enabled && Number.isFinite(batchId) && batchId > 0 && rowId != null && rowId > 0,
  })
}

// Invalidate everything affected by a write within a batch (rows list, single
// row, summary, commit-preview, reverse-check, batch status).
function invalidateBatch(qc: ReturnType<typeof useQueryClient>, batchId: number) {
  void qc.invalidateQueries({ queryKey: ['imports', 'rows', batchId] })
  void qc.invalidateQueries({ queryKey: ['imports', 'row', batchId] })
  void qc.invalidateQueries({ queryKey: keys.summary(batchId) })
  void qc.invalidateQueries({ queryKey: keys.batch(batchId) })
  void qc.invalidateQueries({ queryKey: keys.commitPreview(batchId) })
  void qc.invalidateQueries({ queryKey: ['imports', 'reverse-check', batchId] })
}

export function useReverseRow(batchId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (rowId: number) => reverseRow(batchId, rowId),
    onSuccess: () => invalidateBatch(qc, batchId),
  })
}

export function useCommitBatch(batchId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => commitBatch(batchId),
    onSuccess: () => invalidateBatch(qc, batchId),
  })
}

export function useEditRow(batchId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ rowId, edit }: { rowId: number; edit: ImportRowEdit }) =>
      editRow(batchId, rowId, edit),
    onSuccess: () => invalidateBatch(qc, batchId),
  })
}

export function useRowAction(batchId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ rowId, action, notes }: { rowId: number; action: RowAction; notes?: string }) =>
      rowAction(batchId, rowId, action, notes),
    onSuccess: () => invalidateBatch(qc, batchId),
  })
}

export function useResolveIssue(batchId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ issueId, note }: { issueId: number; note?: string }) =>
      resolveIssue(batchId, issueId, note),
    onSuccess: () => invalidateBatch(qc, batchId),
  })
}

export function useBulkApproveClean(batchId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => bulkApproveClean(batchId),
    onSuccess: () => invalidateBatch(qc, batchId),
  })
}

export function useUploadBatch() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (file: File) => uploadBatch(file),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.batches })
    },
  })
}
