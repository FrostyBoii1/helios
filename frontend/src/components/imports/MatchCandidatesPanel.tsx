// Section B1/B2-3/B3-1 — "Possible same customer" panel for the import row modal.
// B1 surfaced advisory candidates (read-only, with reasons + a confidence band).
// B2-3 makes live-customer candidates ACTIONABLE: when `onUseCustomer` is provided
// (an editable/pending row), a candidate that resolves to an existing live customer
// gets a "Use this customer" action. Batch-row candidates whose sibling hasn't been
// committed yet have no live customer and stay advisory — pending-row linking is not
// supported yet (that is future work). With no action props it renders as the
// original advisory panel.
//
// B3-1 adds a purely cosmetic "Recommended" marker on STRONG candidates (derived
// from the existing B1 confidence band — no new state/decision system). Recommended
// is NOT auto-selected: it never writes resolution and never changes preview/commit/
// reverse — the reviewer still confirms explicitly via "Use this customer".

import { Link } from 'react-router-dom'

import { useRowMatchCandidates } from '@/hooks/useImports'

const CONF_BOX: Record<string, string> = {
  strong: 'border-amber-500/40 bg-amber-500/10',
  medium: 'border-sky-500/30 bg-sky-500/10',
  weak: 'border-line bg-elevated',
}
const CONF_DOT: Record<string, string> = {
  strong: 'bg-amber-400',
  medium: 'bg-sky-400',
  weak: 'bg-slate-400',
}

interface MatchCandidatesPanelProps {
  batchId: number
  rowId: number
  // B2-3 (optional): when provided AND editable, a live-customer candidate shows a
  // "Use this customer" action. Omit (or editable=false) for an advisory panel.
  editable?: boolean
  resolvedCustomerId?: number | null
  onUseCustomer?: (customerId: number) => void
  busy?: boolean
}

export function MatchCandidatesPanel({
  batchId,
  rowId,
  editable = false,
  resolvedCustomerId = null,
  onUseCustomer,
  busy = false,
}: MatchCandidatesPanelProps) {
  const { data, isLoading } = useRowMatchCandidates(batchId, rowId)
  const candidates = data ?? []
  // Nothing to show: no candidates (or still loading) — stay out of the way.
  if (isLoading || candidates.length === 0) return null
  const actionable = editable && typeof onUseCustomer === 'function'

  return (
    <section className="rounded-md border border-amber-500/30 bg-amber-500/[0.06] p-3">
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-amber-300">
          Possible same customer ({candidates.length})
        </h3>
        <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-amber-200/80">
          {actionable ? 'Pick to attach' : 'Advisory'}
        </span>
      </div>
      <p className="mb-2 text-xs text-amber-200/70">
        {actionable
          ? 'Attach this job to an existing customer, or leave it to create a new one. Only existing live customers can be selected.'
          : 'This row may belong to an existing customer or another row in this batch. Review only.'}
      </p>
      <ul className="flex flex-col gap-1.5">
        {candidates.map((c, i) => {
          // customer_id is set for live_customer candidates and for batch-row
          // candidates whose sibling has already been committed (a live customer).
          const liveId = c.customer_id
          const selected = liveId != null && liveId === resolvedCustomerId
          const selectable = actionable && liveId != null && !selected
          return (
            <li key={i} className={`rounded border px-2 py-1.5 text-xs ${CONF_BOX[c.confidence]}`}>
              <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${CONF_DOT[c.confidence]}`} />
                <span className="font-medium text-fg">{c.name || '(no name)'}</span>
                <span className="text-[10px] uppercase tracking-wide text-faint">{c.confidence}</span>
                {/* B3-1: cosmetic "Recommended" marker on strong candidates only.
                    Advisory — it never auto-selects; the reviewer still confirms. */}
                {c.confidence === 'strong' && (
                  <span
                    className="rounded bg-amber-500/20 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-200"
                    title="High-confidence match — recommended, but never auto-selected. Confirm explicitly with “Use this customer”."
                  >
                    ★ Recommended
                  </span>
                )}
                {liveId != null ? (
                  <Link
                    to={`/customers/${liveId}`}
                    onClick={(e) => e.stopPropagation()}
                    className="text-brand-400 hover:underline"
                  >
                    existing customer #{liveId}
                  </Link>
                ) : (
                  <span className="text-faint">batch row #{c.source_row_index}</span>
                )}
                {/* B2-3 action / state (only on an editable row). */}
                {actionable && (
                  <span className="ml-auto">
                    {selected ? (
                      <span className="font-medium text-emerald-300">Selected ✓</span>
                    ) : selectable ? (
                      <button
                        type="button"
                        onClick={() => onUseCustomer!(liveId!)}
                        disabled={busy}
                        className="rounded border border-brand-500/40 bg-brand-500/10 px-2 py-0.5 font-medium text-brand-200 hover:bg-brand-500/20 disabled:opacity-50"
                      >
                        Use this customer
                      </button>
                    ) : (
                      <span
                        className="text-faint"
                        title="This batch row hasn't been committed yet, so it has no live customer to attach to."
                      >
                        pending — can’t select yet
                      </span>
                    )}
                  </span>
                )}
              </div>
              <div className="mt-0.5 break-words text-faint">{c.reasons.join(' · ')}</div>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
