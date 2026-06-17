// Section D: confirm "Prepare recommit" for a reversed row. This clears the row's
// committed links (prior ids preserved in an audit Activity), detaches any group, resets
// resolution, and returns the row to Pending — it does NOT approve or commit, and never
// touches the soft-deleted Job/Customer. A recommit creates brand-new records on commit.

import { useState } from 'react'
import { ApiError } from '@/lib/api'
import { usePrepareRecommit } from '@/hooks/useImports'
import type { ImportRow } from '@/types/imports'

interface PrepareRecommitModalProps {
  batchId: number
  rowId: number
  /** Show the extra group-detach warning when the reversed row was grouped. */
  grouped: boolean
  onClose: () => void
  onPrepared: (row: ImportRow) => void
}

export function PrepareRecommitModal({
  batchId,
  rowId,
  grouped,
  onClose,
  onPrepared,
}: PrepareRecommitModalProps) {
  const mutation = usePrepareRecommit(batchId)
  const [error, setError] = useState<string | null>(null)

  async function handleConfirm() {
    setError(null)
    try {
      const row = await mutation.mutateAsync(rowId)
      onPrepared(row)
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setError('You do not have permission to prepare recommits.')
      } else if (err instanceof ApiError && err.status === 409) {
        setError('This row is no longer reversed, so it cannot be prepared for recommit.')
      } else if (err instanceof ApiError && err.status === 404) {
        setError('This row no longer exists.')
      } else {
        setError('Prepare recommit failed. Please try again.')
      }
    }
  }

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/60 px-4"
      role="dialog"
      aria-modal="true"
    >
      <div className="card w-full max-w-md p-6 shadow-2xl shadow-black/40">
        <h2 className="mb-3 text-lg font-semibold text-fg">Prepare this row for recommit?</h2>

        {error && (
          <div className="mb-4 rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
            {error}
          </div>
        )}

        <p className="text-sm text-muted">
          This creates a new Customer/Job on commit. The reversed records stay deleted for
          audit. The row returns to Pending for review.
        </p>
        {grouped && (
          <p className="mt-2 text-sm text-amber-300">
            This row will be detached from its group. Re-resolve or re-group before approving.
          </p>
        )}

        <div className="mt-6 flex justify-end gap-3">
          <button onClick={onClose} className="btn-secondary">
            Cancel
          </button>
          <button
            onClick={handleConfirm}
            disabled={mutation.isPending}
            className="btn-primary disabled:opacity-50"
          >
            {mutation.isPending ? 'Preparing…' : 'Prepare recommit'}
          </button>
        </div>
      </div>
    </div>
  )
}
