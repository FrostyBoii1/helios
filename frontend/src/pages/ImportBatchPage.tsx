import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  useImportBatch,
  useImportCommitPreview,
  useImportRows,
  useImportSummary,
} from '@/hooks/useImports'
import { ImportRowTable } from '@/components/imports/ImportRowTable'
import { ImportRowModal } from '@/components/imports/ImportRowModal'
import { BulkApproveCleanModal } from '@/components/imports/BulkApproveCleanModal'
import { CommitModal } from '@/components/imports/CommitModal'
import {
  REVIEW_STATUS_LABELS,
  REVIEW_STATUS_ORDER,
  ROW_CLASS_LABELS,
  ROW_CLASS_ORDER,
} from '@/components/imports/ReviewStatusBadge'
import { SEVERITY_LABELS, SEVERITY_ORDER } from '@/components/imports/IssueBadges'
import type {
  ImportIssueSeverity,
  ImportRowClass,
  ImportRowReviewStatus,
} from '@/types/imports'

const PAGE_SIZE = 50

export function ImportBatchPage() {
  const params = useParams<{ id: string }>()
  const batchId = Number(params.id)

  const [rowClass, setRowClass] = useState<ImportRowClass | ''>('')
  const [reviewStatus, setReviewStatus] = useState<ImportRowReviewStatus | ''>('')
  const [severity, setSeverity] = useState<ImportIssueSeverity | ''>('')
  const [unresolvedOnly, setUnresolvedOnly] = useState(false)
  const [searchInput, setSearchInput] = useState('')
  const [q, setQ] = useState('')
  const [offset, setOffset] = useState(0)
  const [openRowId, setOpenRowId] = useState<number | null>(null)
  const [showBulk, setShowBulk] = useState(false)
  const [showCommit, setShowCommit] = useState(false)
  const [bulkMessage, setBulkMessage] = useState<string | null>(null)

  // Debounce search; reset to the first page on a new query.
  useEffect(() => {
    const handle = setTimeout(() => {
      setQ(searchInput.trim())
      setOffset(0)
    }, 300)
    return () => clearTimeout(handle)
  }, [searchInput])

  const batchQuery = useImportBatch(batchId)
  const summaryQuery = useImportSummary(batchId)
  const commitPreviewQuery = useImportCommitPreview(batchId)
  const eligibleToCommit = commitPreviewQuery.data?.eligible_count ?? 0
  const rowsQuery = useImportRows(batchId, {
    row_class: rowClass || undefined,
    review_status: reviewStatus || undefined,
    severity: severity || undefined,
    unresolved_only: unresolvedOnly || undefined,
    q: q || undefined,
    limit: PAGE_SIZE,
    offset,
  })

  const total = rowsQuery.data?.total ?? 0
  const pageInfo = useMemo(() => {
    if (total === 0) return '0 rows'
    return `${offset + 1}–${Math.min(offset + PAGE_SIZE, total)} of ${total}`
  }, [offset, total])

  const hasFilters = !!(rowClass || reviewStatus || severity || unresolvedOnly || q)

  function resetPageThen(fn: () => void) {
    fn()
    setOffset(0)
  }

  if (Number.isNaN(batchId)) {
    return <div className="card p-6 text-sm text-red-300">Invalid batch id.</div>
  }

  return (
    <div>
      <div className="mb-4">
        <Link to="/imports" className="text-sm text-brand-400 hover:underline">
          ← All imports
        </Link>
      </div>

      {/* Header / batch meta */}
      {batchQuery.isLoading ? (
        <div className="card p-6 text-sm text-muted">Loading batch…</div>
      ) : batchQuery.isError || !batchQuery.data ? (
        <div className="card border-red-500/30 p-6 text-sm text-red-300">
          Could not load this batch.
        </div>
      ) : (
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold text-fg">{batchQuery.data.source_filename}</h1>
            <p className="text-sm text-muted">
              {batchQuery.data.sheet_name} · status{' '}
              <span className="uppercase tracking-wide">{batchQuery.data.status}</span> ·{' '}
              {batchQuery.data.total_rows} rows
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => {
                setBulkMessage(null)
                setShowBulk(true)
              }}
              className="btn-secondary"
              disabled={(summaryQuery.data?.eligible_clean_count ?? 0) === 0}
              title={
                (summaryQuery.data?.eligible_clean_count ?? 0) === 0
                  ? 'No clean rows are eligible right now.'
                  : undefined
              }
            >
              Approve clean ({summaryQuery.data?.eligible_clean_count ?? 0})
            </button>
            <button
              onClick={() => setShowCommit(true)}
              className="btn-primary disabled:opacity-50"
              disabled={eligibleToCommit === 0}
              title={
                eligibleToCommit === 0
                  ? 'No approved rows are ready to commit.'
                  : 'Create live Customer/Job records from approved rows'
              }
            >
              Commit to live ({eligibleToCommit})
            </button>
          </div>
        </div>
      )}

      {bulkMessage && (
        <div className="mb-4 rounded-md border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300">
          {bulkMessage}
        </div>
      )}

      {/* Progress / summary */}
      {summaryQuery.data && <SummaryBar summary={summaryQuery.data} />}

      {/* Filters */}
      <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:flex-wrap lg:items-center">
        <input
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          placeholder="Search reference or customer name…"
          className="input lg:flex-1"
        />
        <select
          value={rowClass}
          onChange={(e) => resetPageThen(() => setRowClass(e.target.value as ImportRowClass | ''))}
          className="input lg:w-44"
        >
          <option value="">All classes</option>
          {ROW_CLASS_ORDER.map((c) => (
            <option key={c} value={c}>
              {ROW_CLASS_LABELS[c]}
            </option>
          ))}
        </select>
        <select
          value={reviewStatus}
          onChange={(e) =>
            resetPageThen(() => setReviewStatus(e.target.value as ImportRowReviewStatus | ''))
          }
          className="input lg:w-44"
        >
          <option value="">All statuses</option>
          {REVIEW_STATUS_ORDER.map((s) => (
            <option key={s} value={s}>
              {REVIEW_STATUS_LABELS[s]}
            </option>
          ))}
        </select>
        <select
          value={severity}
          onChange={(e) =>
            resetPageThen(() => setSeverity(e.target.value as ImportIssueSeverity | ''))
          }
          className="input lg:w-44"
        >
          <option value="">Any severity</option>
          {SEVERITY_ORDER.map((s) => (
            <option key={s} value={s}>
              {SEVERITY_LABELS[s]}
            </option>
          ))}
        </select>
        <label className="flex items-center gap-2 text-sm text-fg">
          <input
            type="checkbox"
            checked={unresolvedOnly}
            onChange={(e) => resetPageThen(() => setUnresolvedOnly(e.target.checked))}
            className="h-4 w-4 rounded border-line bg-elevated"
          />
          Unresolved errors only
        </label>
      </div>

      <ImportRowTable
        rows={rowsQuery.data?.items ?? []}
        loading={rowsQuery.isLoading}
        error={rowsQuery.isError}
        emptyMessage={hasFilters ? 'No rows match your filters.' : 'This batch has no rows.'}
        onOpenRow={(row) => setOpenRowId(row.id)}
      />

      <div className="mt-3 flex items-center justify-between text-sm text-muted">
        <span>
          {pageInfo}
          {rowsQuery.isFetching && !rowsQuery.isLoading ? ' · updating…' : ''}
        </span>
        <div className="flex gap-2">
          <button
            disabled={offset === 0}
            onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
            className="rounded-md border border-line-strong px-3 py-1 text-fg hover:bg-elevated disabled:opacity-50"
          >
            Previous
          </button>
          <button
            disabled={offset + PAGE_SIZE >= total}
            onClick={() => setOffset((o) => o + PAGE_SIZE)}
            className="rounded-md border border-line-strong px-3 py-1 text-fg hover:bg-elevated disabled:opacity-50"
          >
            Next
          </button>
        </div>
      </div>

      {openRowId != null && (
        <ImportRowModal
          batchId={batchId}
          rowId={openRowId}
          onClose={() => setOpenRowId(null)}
        />
      )}

      {showBulk && (
        <BulkApproveCleanModal
          batchId={batchId}
          eligibleCount={summaryQuery.data?.eligible_clean_count ?? 0}
          onClose={() => setShowBulk(false)}
          onApplied={(approved) => {
            setShowBulk(false)
            setBulkMessage(`Approved ${approved} clean ${approved === 1 ? 'row' : 'rows'}.`)
          }}
        />
      )}

      {showCommit && <CommitModal batchId={batchId} onClose={() => setShowCommit(false)} />}
    </div>
  )
}

function SummaryBar({
  summary,
}: {
  summary: import('@/types/imports').ImportBatchSummary
}) {
  const reviewed =
    (summary.by_review_status.approved ?? 0) +
    (summary.by_review_status.rejected ?? 0) +
    (summary.by_review_status.skipped ?? 0)
  const approvable =
    (summary.by_row_class.job ?? 0) + (summary.by_row_class.ambiguous ?? 0)
  const pct = approvable > 0 ? Math.round((reviewed / approvable) * 100) : 0

  return (
    <div className="card mb-4 p-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-sm">
        <span className="text-muted">
          Review progress:{' '}
          <span className="font-medium text-fg">
            {reviewed}/{approvable}
          </span>{' '}
          approvable rows actioned
        </span>
        <span className="text-faint">
          {summary.unresolved_error_rows} rows with unresolved errors
        </span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-elevated">
        <div className="h-full rounded-full bg-brand-500" style={{ width: `${pct}%` }} />
      </div>
      <div className="mt-3 flex flex-wrap gap-3 text-xs text-muted">
        {REVIEW_STATUS_ORDER.map((s) => (
          <span key={s}>
            {REVIEW_STATUS_LABELS[s]}:{' '}
            <span className="text-fg">{summary.by_review_status[s] ?? 0}</span>
          </span>
        ))}
      </div>
    </div>
  )
}
