// TanStack Query hooks for import staging/review.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  addGroupRow,
  bulkApproveClean,
  commitBatch,
  createCustomerGroup,
  dissolveCustomerGroup,
  editRow,
  getBatch,
  getBatchSummary,
  getCommitPreview,
  getCustomerGroup,
  getFieldRegistry,
  getReverseCheck,
  getRow,
  getRowMatchCandidates,
  listBatches,
  listRows,
  prepareRecommit,
  removeGroupRow,
  resolveIssue,
  resolveRowCustomer,
  reverseRow,
  rowAction,
  setGroupPrimary,
  uploadBatch,
  type RowAction,
} from '@/lib/imports'
import type { CustomerResolutionRequest, ImportRowEdit, ListRowsParams } from '@/types/imports'

const keys = {
  all: ['imports'] as const,
  fieldRegistry: ['imports', 'field-registry'] as const,
  batches: ['imports', 'batches'] as const,
  batch: (id: number) => ['imports', 'batch', id] as const,
  summary: (id: number) => ['imports', 'summary', id] as const,
  rows: (id: number, params: ListRowsParams) => ['imports', 'rows', id, params] as const,
  row: (batchId: number, rowId: number) => ['imports', 'row', batchId, rowId] as const,
  matchCandidates: (batchId: number, rowId: number) =>
    ['imports', 'match-candidates', batchId, rowId] as const,
  commitPreview: (id: number) => ['imports', 'commit-preview', id] as const,
  reverseCheck: (batchId: number, rowId: number) =>
    ['imports', 'reverse-check', batchId, rowId] as const,
  customerGroup: (batchId: number, groupId: number) =>
    ['imports', 'customer-group', batchId, groupId] as const,
}

export function useFieldRegistry() {
  // Static metadata — cache aggressively; one fetch drives the structured UI.
  return useQuery({
    queryKey: keys.fieldRegistry,
    queryFn: getFieldRegistry,
    staleTime: Infinity,
    gcTime: Infinity,
  })
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

// Section B1: advisory same-customer candidates for the open row (read-only).
export function useRowMatchCandidates(batchId: number, rowId: number | null) {
  return useQuery({
    queryKey: keys.matchCandidates(batchId, rowId ?? 0),
    queryFn: () => getRowMatchCandidates(batchId, rowId as number),
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
  // Stabilization (C): same-customer candidates change after a commit/resolve/group
  // edit (e.g. once a sibling commits, its row collapses into one deduped existing
  // customer candidate, and a newly-grouped candidate becomes "Join this group").
  // refetchType:'all' refreshes EVERY candidate panel — including ones not currently
  // mounted — so a stale row-level group/use action can't survive a batch change.
  void qc.invalidateQueries({ queryKey: ['imports', 'match-candidates', batchId], refetchType: 'all' })
  // B3-4: group reads (banner) — membership may have changed.
  void qc.invalidateQueries({ queryKey: ['imports', 'customer-group', batchId] })
  // Item 3: an import write (commit / reverse / prepare-recommit / recommit) can create,
  // soft-delete, re-promote, or attach LIVE records — affecting CRM read models these
  // import queries don't otherwise touch. A grouped commit/reverse can touch the promoted
  // primary plus any attach-to-existing customers, so broad prefixes (not a single id)
  // refresh the Customer detail, Jobs panel/list, and Timeline immediately instead of
  // after staleTime. Only currently-mounted queries refetch, so this is cheap.
  void qc.invalidateQueries({ queryKey: ['customers'] })
  void qc.invalidateQueries({ queryKey: ['jobs'] })
  void qc.invalidateQueries({ queryKey: ['activities'] })
}

export function useReverseRow(batchId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (rowId: number) => reverseRow(batchId, rowId),
    onSuccess: () => invalidateBatch(qc, batchId),
  })
}

// Section D: prepare a reversed row for recommit. On success the row returns to
// Pending, so invalidating the batch re-renders the drawer into the normal review UI.
export function usePrepareRecommit(batchId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (rowId: number) => prepareRecommit(batchId, rowId),
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

// Section B2-3: set/clear a row's manual same-customer resolution. invalidateBatch
// refetches the row + commit-preview so attach-vs-create reflects the new state.
export function useResolveRowCustomer(batchId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ rowId, payload }: { rowId: number; payload: CustomerResolutionRequest }) =>
      resolveRowCustomer(batchId, rowId, payload),
    onSuccess: () => invalidateBatch(qc, batchId),
  })
}

// ---- Section B3-4: pending-row groups ----
export function useCustomerGroup(batchId: number, groupId: number | null) {
  return useQuery({
    queryKey: keys.customerGroup(batchId, groupId ?? 0),
    queryFn: () => getCustomerGroup(batchId, groupId as number),
    enabled: Number.isFinite(batchId) && batchId > 0 && groupId != null && groupId > 0,
  })
}

export function useCreateCustomerGroup(batchId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ primaryRowId, memberRowIds, reason }: { primaryRowId: number; memberRowIds: number[]; reason?: string | null }) =>
      createCustomerGroup(batchId, primaryRowId, memberRowIds, reason),
    onSuccess: () => invalidateBatch(qc, batchId),
  })
}

export function useAddGroupRow(batchId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ groupId, rowId }: { groupId: number; rowId: number }) =>
      addGroupRow(batchId, groupId, rowId),
    onSuccess: () => invalidateBatch(qc, batchId),
  })
}

export function useRemoveGroupRow(batchId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ groupId, rowId }: { groupId: number; rowId: number }) =>
      removeGroupRow(batchId, groupId, rowId),
    onSuccess: () => invalidateBatch(qc, batchId),
  })
}

export function useSetGroupPrimary(batchId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ groupId, primaryRowId }: { groupId: number; primaryRowId: number }) =>
      setGroupPrimary(batchId, groupId, primaryRowId),
    onSuccess: () => invalidateBatch(qc, batchId),
  })
}

export function useDissolveCustomerGroup(batchId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ groupId }: { groupId: number }) => dissolveCustomerGroup(batchId, groupId),
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
