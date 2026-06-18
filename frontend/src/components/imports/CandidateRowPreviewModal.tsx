// Section H2 — read-only preview of a STAGED candidate import row (a batch_row
// candidate that has no live customer yet, e.g. pending Stuart White rows #23/#24).
//
// Lets the reviewer inspect another batch row's parsed/review data WITHOUT leaving the
// current import row, to decide if it is the same customer. STRICTLY READ-ONLY: it
// composes the existing read-only GET hook useImportRow (GET /imports/{batch}/rows/{id})
// and holds NO action callbacks — no approve/reject/skip/group/join/use-customer and no
// mutation. Its only controls are dismissal (✕ / Escape / backdrop / Close). Any
// committed-customer link opens in a NEW tab so the current import row is never left.

import { useEffect } from 'react'
import { Link } from 'react-router-dom'

import { useImportRow } from '@/hooks/useImports'
import type { SiteAddress } from '@/types/imports'

interface CandidateRowPreviewModalProps {
  batchId: number
  rowId: number
  candidateName: string
  onClose: () => void
}

const STATUS_LABEL: Record<string, string> = {
  pending: 'Pending', approved: 'Approved', rejected: 'Rejected',
  skipped: 'Skipped', committed: 'Committed', reversed: 'Reversed',
}

/** "line1, line2, Suburb STATE postcode" from the parsed site address, or '' if none. */
function siteLine(s: SiteAddress | null | undefined): string {
  if (!s) return ''
  const city = [s.suburb, s.state, s.postcode].map((p) => (p ? String(p).trim() : '')).filter(Boolean).join(' ')
  return [s.line1, s.line2, city].map((p) => (p ? String(p).trim() : '')).filter(Boolean).join(', ')
}

export function CandidateRowPreviewModal({
  batchId,
  rowId,
  candidateName,
  onClose,
}: CandidateRowPreviewModalProps) {
  const rowQ = useImportRow(batchId, rowId)

  // Escape closes (read-only dismissal only).
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const row = rowQ.data
  const parsed = row?.parsed ?? null
  const site = parsed?.details?.site ?? null
  const siteStr = siteLine(site)
  const emails = (parsed?.emails ?? []).filter(Boolean)
  const phones = (parsed?.phones ?? []).filter(Boolean)
  const importedContext = row?.internal_notes_override || row?.context_text || ''

  return (
    // z-40 so the preview floats above the import row modal (z-30).
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/60 px-4"
      role="dialog"
      aria-modal="true"
      aria-label="Candidate row preview"
      onClick={onClose}
    >
      <div
        className="card flex max-h-[85vh] w-full max-w-2xl flex-col p-0 shadow-2xl shadow-black/40"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-3">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-base font-semibold text-fg">
                {parsed?.customer_name || candidateName || '(no name)'}
              </h2>
              <span className="rounded bg-elevated px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-faint">
                Read-only preview
              </span>
              {row && (
                <span className="rounded bg-elevated px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-muted">
                  {STATUS_LABEL[row.review_status] ?? row.review_status}
                </span>
              )}
            </div>
            <p className="mt-0.5 text-xs text-muted">
              Staged import row{row ? ` #${row.source_row_index}` : ''}
              {row?.legacy_reference ? ` · ref ${row.legacy_reference}` : ''}
              {row ? ` · ${row.row_class}` : ''}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-muted hover:bg-elevated hover:text-fg"
            aria-label="Close preview"
          >
            ✕
          </button>
        </div>

        {/* Body */}
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          {rowQ.isLoading ? (
            <p className="text-sm text-muted">Loading candidate row…</p>
          ) : rowQ.isError || !row ? (
            <p className="text-sm text-red-300">Could not load this candidate row.</p>
          ) : (
            <dl className="grid grid-cols-[7rem_1fr] gap-x-3 gap-y-1.5 text-sm">
              <dt className="text-faint">Address</dt>
              <dd className="break-words text-fg">{siteStr || parsed?.address || '—'}</dd>
              {site?.note && (
                <>
                  <dt className="text-faint">Address note</dt>
                  <dd className="break-words text-fg">{site.note}</dd>
                </>
              )}
              <dt className="text-faint">Email</dt>
              <dd className="break-words text-fg">{emails.length ? emails.join(', ') : '—'}</dd>
              <dt className="text-faint">Phone</dt>
              <dd className="text-fg">
                {phones.length
                  ? phones.map((p) => (p.label ? `${p.number} (${p.label})` : p.number)).join(', ')
                  : '—'}
              </dd>
              {(parsed?.sale_date || parsed?.install_date) && (
                <>
                  <dt className="text-faint">Dates</dt>
                  <dd className="text-fg">
                    {[parsed?.sale_date && `sold ${parsed.sale_date}`, parsed?.install_date && `install ${parsed.install_date}`]
                      .filter(Boolean)
                      .join(' · ') || '—'}
                  </dd>
                </>
              )}
              {parsed?.approval_state && (
                <>
                  <dt className="text-faint">Approval</dt>
                  <dd className="text-fg">{parsed.approval_state}</dd>
                </>
              )}
              <dt className="text-faint">Group</dt>
              <dd className="text-fg">
                {row.customer_group_id != null
                  ? `In group #${row.customer_group_id}`
                  : row.customer_resolution_mode
                    ? `Resolution: ${row.customer_resolution_mode}`
                    : 'Not grouped'}
              </dd>
              <dt className="text-faint">Committed</dt>
              <dd className="text-fg">
                {row.committed_customer_id != null ? (
                  <Link
                    to={`/customers/${row.committed_customer_id}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    onClick={(e) => e.stopPropagation()}
                    className="text-brand-400 hover:underline"
                  >
                    customer #{row.committed_customer_id}
                    {row.committed_job_id != null ? ` · job #${row.committed_job_id}` : ''} ↗
                  </Link>
                ) : (
                  'Not committed'
                )}
              </dd>
              {importedContext && (
                <>
                  <dt className="text-faint">Imported context</dt>
                  <dd className="whitespace-pre-wrap break-words text-fg">{importedContext}</dd>
                </>
              )}
            </dl>
          )}
        </div>

        {/* Footer — dismissal only; no save/confirm/action. */}
        <div className="flex justify-end border-t border-line px-5 py-3">
          <button type="button" onClick={onClose} className="btn-secondary">
            Close
          </button>
        </div>
      </div>
    </div>
  )
}
