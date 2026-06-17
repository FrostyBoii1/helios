// Section B1/B2-3/B3-1/B3-4 — "Possible same customer" panel for the import row modal.
// B1 surfaced advisory candidates (read-only, with reasons + a confidence band).
// B2-3 makes LIVE-customer candidates actionable: "Use this customer" attaches the
// job to an existing customer. B3-4 makes PENDING batch-row candidates actionable too:
// "Group as same customer" puts this row + the candidate row into one future-customer
// group. The two actions are visually distinct (brand = attach existing, indigo =
// group pending). B3-1 keeps the cosmetic "Recommended" marker on strong candidates.
// With no action props it renders as the original advisory panel.

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
  editable?: boolean
  // B2-3: attach this row to a live customer candidate.
  resolvedCustomerId?: number | null
  onUseCustomer?: (customerId: number) => void
  // B3-4: group this row with a PENDING batch-row candidate (no live customer yet).
  onGroupWithRow?: (candidateRowId: number) => void
  // B (stabilization): join THIS row to the candidate's EXISTING group (preserving
  // that group's primary) instead of stealing the candidate into a new group.
  onJoinGroup?: (groupId: number) => void
  // Row ids already in THIS row's group (shown as "In group ✓").
  groupMemberRowIds?: number[]
  busy?: boolean
}

export function MatchCandidatesPanel({
  batchId,
  rowId,
  editable = false,
  resolvedCustomerId = null,
  onUseCustomer,
  onGroupWithRow,
  onJoinGroup,
  groupMemberRowIds = [],
  busy = false,
}: MatchCandidatesPanelProps) {
  const { data, isLoading } = useRowMatchCandidates(batchId, rowId)
  const candidates = data ?? []
  if (isLoading || candidates.length === 0) return null

  const canUse = editable && typeof onUseCustomer === 'function'
  const canGroup = editable && typeof onGroupWithRow === 'function'
  const canJoin = editable && typeof onJoinGroup === 'function'
  const actionable = canUse || canGroup
  const memberSet = new Set(groupMemberRowIds)

  return (
    <section className="rounded-md border border-amber-500/30 bg-amber-500/[0.06] p-3">
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-amber-300">
          Possible same customer ({candidates.length})
        </h3>
        <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-amber-200/80">
          {actionable ? 'Pick / group' : 'Advisory'}
        </span>
      </div>
      <p className="mb-2 text-xs text-amber-200/70">
        {actionable
          ? 'Attach to an existing customer (Use this customer), or group with another pending row to become one new customer (Group as same customer).'
          : 'This row may belong to an existing customer or another row in this batch. Review only.'}
      </p>
      <ul className="flex flex-col gap-1.5">
        {candidates.map((c, i) => {
          const liveId = c.customer_id // set for live_customer + already-committed batch rows
          const selected = liveId != null && liveId === resolvedCustomerId
          const inGroup = c.row_id != null && memberSet.has(c.row_id)
          return (
            <li key={i} className={`rounded border px-2 py-1.5 text-xs ${CONF_BOX[c.confidence]}`}>
              <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${CONF_DOT[c.confidence]}`} />
                <span className="font-medium text-fg">{c.name || '(no name)'}</span>
                <span className="text-[10px] uppercase tracking-wide text-faint">{c.confidence}</span>
                {/* B3-1: cosmetic "Recommended" marker on strong candidates only. */}
                {c.confidence === 'strong' && (
                  <span
                    className="rounded bg-amber-500/20 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-200"
                    title="High-confidence match — recommended, but never auto-selected."
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
                {/* Action (only on an editable row). */}
                {actionable && (
                  <span className="ml-auto">
                    {liveId != null ? (
                      // B2: live customer -> attach.
                      selected ? (
                        <span className="font-medium text-emerald-300">Selected ✓</span>
                      ) : canUse ? (
                        <button
                          type="button"
                          onClick={() => onUseCustomer!(liveId)}
                          disabled={busy}
                          className="rounded border border-brand-500/40 bg-brand-500/10 px-2 py-0.5 font-medium text-brand-200 hover:bg-brand-500/20 disabled:opacity-50"
                        >
                          Use this customer
                        </button>
                      ) : null
                    ) : c.row_id != null && canGroup ? (
                      // B3: pending batch row -> group as one future customer.
                      inGroup ? (
                        <span className="font-medium text-indigo-300">In group ✓</span>
                      ) : c.customer_group_id != null && canJoin ? (
                        // B (stabilization): the candidate already belongs to a group —
                        // JOIN it (keeping its primary), never steal the candidate out.
                        <button
                          type="button"
                          onClick={() => onJoinGroup!(c.customer_group_id!)}
                          disabled={busy}
                          className="rounded border border-indigo-500/40 bg-indigo-500/10 px-2 py-0.5 font-medium text-indigo-200 hover:bg-indigo-500/20 disabled:opacity-50"
                        >
                          Join this group
                        </button>
                      ) : (
                        <button
                          type="button"
                          onClick={() => onGroupWithRow!(c.row_id!)}
                          disabled={busy}
                          className="rounded border border-indigo-500/40 bg-indigo-500/10 px-2 py-0.5 font-medium text-indigo-200 hover:bg-indigo-500/20 disabled:opacity-50"
                        >
                          Group as same customer
                        </button>
                      )
                    ) : (
                      <span className="text-faint">review only</span>
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
