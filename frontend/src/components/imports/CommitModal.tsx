// Commit-to-live modal (Phase C2): shows the read-only commit preview, then
// commits the next eligible rows (backend-capped at 25) and shows the result.
// Creating live Customer/Job records is gated behind an explicit confirm here.

import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError } from '@/lib/api'
import { useCommitBatch, useImportCommitPreview } from '@/hooks/useImports'
import type { ImportCommitPreview, ImportCommitResult } from '@/types/imports'

const CAP = 25

const EXCLUDED_LABELS: Record<string, string> = {
  already_committed: 'Already committed',
  blank_or_divider: 'Blank / divider',
  not_approved: 'Not approved',
  unresolved_error: 'Unresolved error',
  missing_customer_name: 'Missing customer name',
  invalid_case_year: 'Invalid case year',
}

interface CommitModalProps {
  batchId: number
  onClose: () => void
}

export function CommitModal({ batchId, onClose }: CommitModalProps) {
  const previewQuery = useImportCommitPreview(batchId)
  const mutation = useCommitBatch(batchId)
  const [result, setResult] = useState<ImportCommitResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function runCommit() {
    setError(null)
    try {
      const res = await mutation.mutateAsync()
      setResult(res)
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setError('You do not have permission to commit imports.')
      } else if (err instanceof ApiError && typeof err.detail === 'string') {
        setError(err.detail)
      } else {
        setError('Commit failed. Please try again.')
      }
    }
  }

  return (
    <div
      className="fixed inset-0 z-30 flex items-center justify-center bg-black/60 px-4"
      role="dialog"
      aria-modal="true"
    >
      <div className="card flex max-h-[90vh] w-full max-w-lg flex-col p-6 shadow-2xl shadow-black/40">
        <h2 className="mb-3 text-lg font-semibold text-fg">Commit approved rows to live records</h2>

        {error && (
          <div className="mb-4 rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
            {error}
          </div>
        )}

        <div className="-mx-1 flex-1 overflow-y-auto px-1">
          {result ? (
            <ResultView result={result} />
          ) : previewQuery.isLoading ? (
            <p className="text-sm text-muted">Loading preview…</p>
          ) : previewQuery.isError || !previewQuery.data ? (
            <p className="text-sm text-red-300">Could not load the commit preview.</p>
          ) : (
            <PreviewView preview={previewQuery.data} />
          )}
        </div>

        <Footer
          result={result}
          preview={previewQuery.data}
          pending={mutation.isPending}
          onCommit={runCommit}
          onClose={onClose}
        />
      </div>
    </div>
  )
}

function PreviewView({ preview }: { preview: ImportCommitPreview }) {
  const eligible = preview.eligible_count
  const excluded = Object.entries(preview.excluded).filter(([, n]) => n > 0)
  return (
    <div className="space-y-4 text-sm">
      <div className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-amber-200">
        This creates <span className="font-semibold">live Customer and Job records</span> and cannot
        be undone here. Up to <span className="font-semibold">{CAP}</span> rows are committed per
        click, in date order.
      </div>

      <div className="flex flex-wrap gap-x-6 gap-y-1">
        <span className="text-muted">
          Eligible: <span className="font-semibold text-fg">{eligible}</span>
        </span>
        <span className="text-muted">
          This call commits: <span className="font-semibold text-fg">{Math.min(CAP, eligible)}</span>
        </span>
        <span className="text-muted">
          Remaining after: <span className="text-fg">{Math.max(0, eligible - CAP)}</span>
        </span>
      </div>

      {excluded.length > 0 && (
        <div>
          <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">
            Not committed
          </h3>
          <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
            {excluded.map(([key, n]) => (
              <li key={key}>
                {EXCLUDED_LABELS[key] ?? key}: <span className="text-fg">{n}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div>
        <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">
          Predicted case numbers
        </h3>
        <p className="mb-2 text-xs text-faint">
          Estimated — the final numbers are assigned at commit time and may differ.
        </p>
        {preview.samples.length === 0 ? (
          <p className="text-xs text-faint">No eligible rows to preview.</p>
        ) : (
          <ul className="space-y-1">
            {preview.samples.slice(0, 8).map((s) => (
              <li key={s.row_id} className="flex justify-between gap-3 text-xs">
                <span className="text-muted">
                  {s.legacy_reference || `Row ${s.source_row_index}`} ·{' '}
                  <span className="text-fg">{s.customer.full_name || '(no name)'}</span>
                </span>
                <span className="font-mono text-brand-300">~{s.predicted_case_number}</span>
              </li>
            ))}
            {preview.samples.length > 8 && (
              <li className="text-xs text-faint">+{preview.samples.length - 8} more…</li>
            )}
          </ul>
        )}
      </div>
    </div>
  )
}

function ResultView({ result }: { result: ImportCommitResult }) {
  return (
    <div className="space-y-4 text-sm">
      <div className="flex flex-wrap gap-x-6 gap-y-1">
        <Stat label="Committed" value={result.committed} tone="emerald" />
        <Stat label="Skipped" value={result.skipped} tone="amber" />
        <Stat label="Failed" value={result.failed} tone="red" />
        <Stat label="Remaining eligible" value={result.remaining_eligible} />
      </div>
      <p className="text-xs text-faint">Batch status: {result.batch_status}</p>

      <ul className="space-y-1">
        {result.results.map((r) => (
          <li
            key={r.row_id}
            className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-line bg-elevated px-3 py-1.5 text-xs"
          >
            <span className="text-muted">
              {r.legacy_reference || `Row ${r.source_row_index ?? r.row_id}`}
            </span>
            {r.status === 'committed' ? (
              <span className="flex items-center gap-2">
                <span className="font-mono text-emerald-300">{r.case_number}</span>
                {r.job_id != null && (
                  <Link to={`/jobs/${r.job_id}`} className="text-brand-400 hover:underline">
                    View job
                  </Link>
                )}
              </span>
            ) : (
              <span className={r.status === 'failed' ? 'text-red-300' : 'text-amber-300'}>
                {r.status}
                {r.reason ? ` · ${r.reason}` : ''}
                {r.error ? ` · ${r.error}` : ''}
              </span>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: string }) {
  const color =
    tone === 'emerald'
      ? 'text-emerald-300'
      : tone === 'amber'
        ? 'text-amber-300'
        : tone === 'red'
          ? 'text-red-300'
          : 'text-fg'
  return (
    <span className="text-muted">
      {label}: <span className={`font-semibold ${color}`}>{value}</span>
    </span>
  )
}

function Footer({
  result,
  preview,
  pending,
  onCommit,
  onClose,
}: {
  result: ImportCommitResult | null
  preview: ImportCommitPreview | undefined
  pending: boolean
  onCommit: () => void
  onClose: () => void
}) {
  if (result) {
    const canContinue = result.remaining_eligible > 0
    return (
      <div className="mt-5 flex justify-end gap-3">
        <button onClick={onClose} className="btn-secondary">
          Done
        </button>
        {canContinue && (
          <button onClick={onCommit} disabled={pending} className="btn-primary disabled:opacity-50">
            {pending ? 'Committing…' : 'Commit next 25'}
          </button>
        )}
      </div>
    )
  }

  const eligible = preview?.eligible_count ?? 0
  const n = Math.min(CAP, eligible)
  return (
    <div className="mt-5 flex justify-end gap-3">
      <button onClick={onClose} className="btn-secondary">
        Cancel
      </button>
      <button
        onClick={onCommit}
        disabled={pending || eligible === 0}
        className="btn-primary disabled:opacity-50"
      >
        {pending ? 'Committing…' : `Commit next ${n}`}
      </button>
    </div>
  )
}
