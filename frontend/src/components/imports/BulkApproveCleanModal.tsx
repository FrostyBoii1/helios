// Confirmation modal for "bulk approve clean": shows how many rows are eligible
// (pending job/ambiguous with no unresolved error) before applying.

import { useState } from 'react'
import { ApiError } from '@/lib/api'
import { useBulkApproveClean } from '@/hooks/useImports'

interface BulkApproveCleanModalProps {
  batchId: number
  eligibleCount: number
  onClose: () => void
  onApplied: (approved: number) => void
}

export function BulkApproveCleanModal({
  batchId,
  eligibleCount,
  onClose,
  onApplied,
}: BulkApproveCleanModalProps) {
  const mutation = useBulkApproveClean(batchId)
  const [error, setError] = useState<string | null>(null)

  async function handleConfirm() {
    setError(null)
    try {
      const result = await mutation.mutateAsync()
      onApplied(result.approved)
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setError('You do not have permission to approve rows.')
      } else {
        setError('Could not approve rows. Please try again.')
      }
    }
  }

  return (
    <div
      className="fixed inset-0 z-30 flex items-center justify-center bg-black/60 px-4"
      role="dialog"
      aria-modal="true"
    >
      <div className="card w-full max-w-md p-6 shadow-2xl shadow-black/40">
        <h2 className="mb-3 text-lg font-semibold text-fg">Approve all clean rows</h2>

        {error && (
          <div className="mb-4 rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
            {error}
          </div>
        )}

        <p className="text-sm text-muted">
          This will approve{' '}
          <span className="font-semibold text-fg">{eligibleCount}</span>{' '}
          pending {eligibleCount === 1 ? 'row' : 'rows'} (job or ambiguous) that have no
          unresolved error-severity issues. Rows with unresolved errors, blanks, and dividers are
          left untouched.
        </p>

        <div className="mt-6 flex justify-end gap-3">
          <button onClick={onClose} className="btn-secondary">
            Cancel
          </button>
          <button
            onClick={handleConfirm}
            disabled={mutation.isPending || eligibleCount === 0}
            className="btn-primary disabled:opacity-50"
          >
            {mutation.isPending ? 'Approving…' : `Approve ${eligibleCount}`}
          </button>
        </div>
      </div>
    </div>
  )
}
