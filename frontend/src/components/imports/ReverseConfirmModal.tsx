// Reverse-confirm modal (Phase C3b). Soft-deleting the created Customer + Job
// is gated behind an explicit confirm here. The backend returns 200 with
// status 'reversed' | 'blocked' (not a 409); a blocked result is shown inline.

import { useState } from 'react'
import { ApiError } from '@/lib/api'
import { useReverseRow } from '@/hooks/useImports'
import { reverseReasonLabel } from '@/components/imports/reverseReasons'
import type { ReverseResult } from '@/types/imports'

interface ReverseConfirmModalProps {
  batchId: number
  rowId: number
  caseNumber: string | null
  onClose: () => void
  onReversed: (result: ReverseResult) => void
}

export function ReverseConfirmModal({
  batchId,
  rowId,
  caseNumber,
  onClose,
  onReversed,
}: ReverseConfirmModalProps) {
  const mutation = useReverseRow(batchId)
  const [error, setError] = useState<string | null>(null)

  async function handleConfirm() {
    setError(null)
    try {
      const res = await mutation.mutateAsync(rowId)
      if (res.status === 'reversed') {
        onReversed(res)
      } else {
        // Re-checked at reverse time and no longer reversible.
        setError(`Can't reverse: ${reverseReasonLabel(res.reason)}`)
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setError('You do not have permission to reverse imports.')
      } else if (err instanceof ApiError && err.status === 404) {
        setError('This row no longer exists.')
      } else {
        setError('Reverse failed. Please try again.')
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
        <h2 className="mb-3 text-lg font-semibold text-fg">Reverse this import?</h2>

        {error && (
          <div className="mb-4 rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
            {error}
          </div>
        )}

        <p className="text-sm text-muted">
          This <span className="font-semibold text-fg">soft-deletes</span> the Customer and Job
          created from this row
          {caseNumber ? (
            <>
              {' '}
              (case <span className="font-mono text-fg">{caseNumber}</span>)
            </>
          ) : null}
          . It's only allowed because those records are untouched since the import.
        </p>

        <div className="mt-6 flex justify-end gap-3">
          <button onClick={onClose} className="btn-secondary">
            Cancel
          </button>
          <button
            onClick={handleConfirm}
            disabled={mutation.isPending}
            className="btn-primary disabled:opacity-50"
          >
            {mutation.isPending ? 'Reversing…' : 'Reverse import'}
          </button>
        </div>
      </div>
    </div>
  )
}
