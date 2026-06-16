// Section B1 — ADVISORY "Possible same customer" panel for the import row modal.
// Read-only: it surfaces candidate customers/rows with reasons + a confidence band
// so a reviewer can spot continuity issues. It performs NO merge/link/resolve and
// has NO action controls — matching is intentionally not enabled yet (B2/B3).

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

export function MatchCandidatesPanel({ batchId, rowId }: { batchId: number; rowId: number }) {
  const { data, isLoading } = useRowMatchCandidates(batchId, rowId)
  const candidates = data ?? []
  // Nothing to show: no candidates (or still loading) — stay out of the way.
  if (isLoading || candidates.length === 0) return null

  return (
    <section className="rounded-md border border-amber-500/30 bg-amber-500/[0.06] p-3">
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-amber-300">
          Possible same customer ({candidates.length})
        </h3>
        <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-amber-200/80">
          Advisory · no action yet
        </span>
      </div>
      <p className="mb-2 text-xs text-amber-200/70">
        This row may belong to an existing customer or another row in this batch. Review
        only — automatic matching/linking is not enabled yet.
      </p>
      <ul className="flex flex-col gap-1.5">
        {candidates.map((c, i) => (
          <li key={i} className={`rounded border px-2 py-1.5 text-xs ${CONF_BOX[c.confidence]}`}>
            <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
              <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${CONF_DOT[c.confidence]}`} />
              <span className="font-medium text-fg">{c.name || '(no name)'}</span>
              <span className="text-[10px] uppercase tracking-wide text-faint">{c.confidence}</span>
              {c.kind === 'live_customer' && c.customer_id != null ? (
                <Link
                  to={`/customers/${c.customer_id}`}
                  onClick={(e) => e.stopPropagation()}
                  className="text-brand-400 hover:underline"
                >
                  existing customer #{c.customer_id}
                </Link>
              ) : (
                <span className="text-faint">batch row #{c.source_row_index}</span>
              )}
            </div>
            <div className="mt-0.5 break-words text-faint">{c.reasons.join(' · ')}</div>
          </li>
        ))}
      </ul>
    </section>
  )
}
