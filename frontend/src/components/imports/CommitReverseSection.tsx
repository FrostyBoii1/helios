// Drawer section for committed/reversed rows (Phase C3b).
//  * committed: "Committed to live" banner + View job + a reverse action gated
//    on the read-only reverse-check (enabled if reversible, disabled with a
//    friendly reason otherwise).
//  * reversed: "Reversed" banner with the committed ids preserved as audit context
//    (no active job link — the job is soft-deleted) + a Section D "Prepare recommit"
//    action that returns the row to Pending so it can be committed again as new records.

import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useReverseCheck } from '@/hooks/useImports'
import { ReverseConfirmModal } from '@/components/imports/ReverseConfirmModal'
import { PrepareRecommitModal } from '@/components/imports/PrepareRecommitModal'
import { reverseReasonLabel } from '@/components/imports/reverseReasons'
import type { ImportRow, ReverseResult } from '@/types/imports'

export function CommitReverseSection({ batchId, row }: { batchId: number; row: ImportRow }) {
  const reversed = row.review_status === 'reversed'
  const committed = row.review_status === 'committed'

  const [showConfirm, setShowConfirm] = useState(false)
  // Case number from the reversal we just performed (the row read has none).
  const [reversedCase, setReversedCase] = useState<string | null>(null)
  // Section D: "Prepare recommit" confirmation for a reversed row.
  const [showPrepare, setShowPrepare] = useState(false)

  // Only committed rows are eligible for a reverse-check (D7).
  const checkQuery = useReverseCheck(batchId, row.id, committed)

  if (reversed) {
    const grouped = row.customer_group_id != null || row.customer_resolution_mode === 'group'
    return (
      <section className="rounded-md border border-line bg-elevated px-3 py-2 text-sm text-muted">
        <span className="font-medium text-fg">Reversed.</span> The Customer and Job created from
        this row were soft-deleted. Prepare a recommit to create new records — the reversed
        records stay deleted for audit.
        <div className="mt-1 text-xs text-faint">
          {reversedCase && (
            <>
              Case <span className="font-mono">{reversedCase}</span> ·{' '}
            </>
          )}
          {row.committed_job_id != null && <>Job #{row.committed_job_id} </>}
          <span className="italic">(removed)</span>
        </div>
        <div className="mt-2">
          <button
            onClick={() => setShowPrepare(true)}
            className="rounded-md border border-brand-500/40 px-3 py-1 text-xs font-medium text-brand-200 transition-colors hover:bg-brand-500/10"
          >
            Prepare recommit
          </button>
        </div>

        {showPrepare && (
          <PrepareRecommitModal
            batchId={batchId}
            rowId={row.id}
            grouped={grouped}
            onClose={() => setShowPrepare(false)}
            // On success the row refetches to 'pending' (the mutation invalidates the
            // batch), so this section unmounts and the drawer shows the normal review UI.
            onPrepared={() => setShowPrepare(false)}
          />
        )}
      </section>
    )
  }

  if (!committed) return null

  const check = checkQuery.data

  function handleReversed(res: ReverseResult) {
    setReversedCase(res.case_number)
    setShowConfirm(false)
    // The row refetches to review_status='reversed' (mutation invalidates it),
    // which re-renders this section into the reversed state above.
  }

  return (
    <section className="rounded-md border border-brand-500/30 bg-brand-500/10 px-3 py-2 text-sm text-brand-200">
      <div>
        <span className="font-medium">Committed to live.</span> This row created a live
        Customer/Job and is now read-only.
        {row.committed_job_id != null && (
          <>
            {' '}
            <Link to={`/jobs/${row.committed_job_id}`} className="text-brand-300 underline">
              View job
            </Link>
          </>
        )}
      </div>

      <div className="mt-2">
        {checkQuery.isLoading ? (
          <span className="text-xs text-faint">Checking whether this can be reversed…</span>
        ) : check?.reversible ? (
          <button
            onClick={() => setShowConfirm(true)}
            className="rounded-md border border-red-500/40 px-3 py-1 text-xs font-medium text-red-300 transition-colors hover:bg-red-500/10"
          >
            Reverse import
          </button>
        ) : (
          <button
            disabled
            title={`Can't reverse: ${reverseReasonLabel(check?.reason ?? null)}`}
            className="cursor-not-allowed rounded-md border border-line px-3 py-1 text-xs font-medium text-faint opacity-60"
          >
            Reverse import
          </button>
        )}
        {check && !check.reversible && (
          <span className="ml-2 text-xs text-amber-300">
            Can't reverse: {reverseReasonLabel(check.reason)}
          </span>
        )}
      </div>

      {showConfirm && (
        <ReverseConfirmModal
          batchId={batchId}
          rowId={row.id}
          caseNumber={check?.case_number ?? null}
          onClose={() => setShowConfirm(false)}
          onReversed={handleReversed}
        />
      )}
    </section>
  )
}
