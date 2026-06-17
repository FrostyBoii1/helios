// Section H — read-only candidate customer preview for the import review modal.
//
// When a "Possible same customer" candidate resolves to an existing (committed)
// customer, the reviewer can open this modal to inspect that customer's identity,
// contact, headline address and jobs (with each job's own site address from
// details.site, shipped in G) BEFORE deciding whether to Use / Group / Join.
//
// STRICTLY READ-ONLY: this component holds NO action callbacks and triggers NO
// mutation. It composes two existing read-only GET hooks — useCustomer(id) and
// useJobs({customer_id}) — and never approves, resolves, groups, joins, commits,
// or reverses anything. Its only interactive controls are dismissal (✕ / Escape /
// backdrop click). All decision actions stay on MatchCandidatesPanel.

import { useEffect } from 'react'

import { JobStatusBadge } from '@/components/JobStatusBadge'
import { LabelChips } from '@/components/LabelChips'
import { useCustomer } from '@/hooks/useCustomers'
import { useJobs } from '@/hooks/useJobs'
import type { Customer, Job } from '@/types'

// Cap the jobs we fetch/show; surface the true total alongside.
const JOB_CAP = 10

interface CandidatePreviewModalProps {
  customerId: number
  candidateName: string
  onClose: () => void
}

/** One job's OWN site address (G details.site): "line1, Suburb STATE" / raw / "—". */
function jobSiteLine(job: Job): string {
  const s = job.details?.site
  if (!s) return '—'
  const line = [s.line1, [s.suburb, s.state].filter(Boolean).join(' ')]
    .map((p) => (p ? String(p).trim() : ''))
    .filter(Boolean)
    .join(', ')
  return line || (s.raw ? String(s.raw).trim() : '') || '—'
}

/** Customer headline address: "line1, line2, Suburb STATE postcode" or '' if none. */
function customerAddressLine(c: Customer): string {
  const cityLine = [c.suburb, c.state, c.postcode].map((p) => p?.trim()).filter(Boolean).join(' ')
  return [c.address_line1, c.address_line2, cityLine]
    .map((p) => (p ? String(p).trim() : ''))
    .filter(Boolean)
    .join(', ')
}

export function CandidatePreviewModal({
  customerId,
  candidateName,
  onClose,
}: CandidatePreviewModalProps) {
  const customerQ = useCustomer(customerId)
  const jobsQ = useJobs({ customer_id: customerId, limit: JOB_CAP })

  // Escape closes (read-only dismissal only — no mutation, no save).
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const customer = customerQ.data
  const jobs = jobsQ.data?.items ?? []
  const total = jobsQ.data?.total ?? 0
  const addr = customer ? customerAddressLine(customer) : ''

  return (
    // z-40 so the preview floats above the import row modal (z-30).
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/60 px-4"
      role="dialog"
      aria-modal="true"
      aria-label="Candidate customer preview"
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
                {customer?.full_name || candidateName || '(no name)'}
              </h2>
              <span className="rounded bg-elevated px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-faint">
                Read-only preview
              </span>
            </div>
            <p className="mt-0.5 text-xs text-muted">Existing customer #{customerId}</p>
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
          {customerQ.isLoading ? (
            <p className="text-sm text-muted">Loading customer…</p>
          ) : customerQ.isError || !customer ? (
            <p className="text-sm text-red-300">Could not load this customer.</p>
          ) : (
            <>
              <dl className="grid grid-cols-[5rem_1fr] gap-x-3 gap-y-1 text-sm">
                <dt className="text-faint">Email</dt>
                <dd className="break-words text-fg">{customer.email || '—'}</dd>
                <dt className="text-faint">Phone</dt>
                <dd className="text-fg">{customer.phone || '—'}</dd>
                <dt className="text-faint">Address</dt>
                <dd className="break-words text-fg">{addr || 'Address not available'}</dd>
              </dl>

              <div className="mt-4">
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">
                  Jobs {!jobsQ.isLoading && total > 0 ? `(${total})` : ''}
                </h3>
                {jobsQ.isLoading ? (
                  <p className="text-sm text-muted">Loading jobs…</p>
                ) : jobsQ.isError ? (
                  <p className="text-sm text-red-300">Could not load jobs.</p>
                ) : jobs.length === 0 ? (
                  <p className="text-sm text-muted">No jobs yet.</p>
                ) : (
                  <ul className="flex flex-col divide-y divide-line/60 rounded border border-line">
                    {jobs.map((job) => (
                      <li
                        key={job.id}
                        className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-sm"
                      >
                        <span className="font-mono text-xs text-brand-400">{job.case_number}</span>
                        <JobStatusBadge status={job.status} />
                        <span className="text-muted">{jobSiteLine(job)}</span>
                        <span className="ml-auto flex items-center gap-2">
                          {job.labels && job.labels.length > 0 && <LabelChips labels={job.labels} />}
                          <span className="whitespace-nowrap text-xs text-faint">
                            {job.install_date ?? job.sale_date ?? '—'}
                          </span>
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
                {total > jobs.length && (
                  <p className="mt-1 text-xs text-faint">
                    Showing {jobs.length} of {total} jobs.
                  </p>
                )}
              </div>
            </>
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
