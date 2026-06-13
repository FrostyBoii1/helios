// Drawer section for committed/reversed rows (Phase C3b).
//  * committed: "Committed to live" banner + View job + a reverse action gated
//    on the read-only reverse-check (enabled if reversible, disabled with a
//    friendly reason otherwise).
//  * reversed: read-only "Reversed" banner with the committed ids preserved as
//    audit context; no active job link (the job is soft-deleted).

import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useReverseCheck } from '@/hooks/useImports'
import { ReverseConfirmModal } from '@/components/imports/ReverseConfirmModal'
import { reverseReasonLabel } from '@/components/imports/reverseReasons'
import type { ImportRow, ReverseResult } from '@/types/imports'

export function CommitReverseSection({ batchId, row }: { batchId: number; row: ImportRow }) {
  const reversed = row.review_status === 'reversed'
  const committed = row.review_status === 'committed'

  const [showConfirm, setShowConfirm] = useState(false)
  // Case number from the reversal we just performed (the row read has none).
  const [reversedCase, setReversedCase] = useState<string | null>(null)

  // Only committed rows are eligible for a reverse-check (D7).
  const checkQuery = useReverseCheck(batchId, row.id, committed)

  if (reversed) {
    return (
      <section className="rounded-md border border-line bg-elevated px-3 py-2 text-sm text-muted">
        <span className="font-medium text-fg">Reversed.</span> The Customer and Job created from
        this row were soft-deleted; this row is read-only.
        <div className="mt-1 text-xs text-faint">
          {reversedCase && (
            <>
              Case <span className="font-mono">{reversedCase}</span> ·{' '}
            </>
          )}
          {row.committed_job_id != null && <>Job #{row.committed_job_id} </>}
          <span className="italic">(removed)</span>
        </div>
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
