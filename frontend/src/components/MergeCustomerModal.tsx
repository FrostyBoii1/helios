// B4-3: admin-only "Merge into..." modal. Search for and select another LIVE
// customer (the winner), review an explicit confirmation/preview of what moves,
// then call the backend merge endpoint. The merge is admin-only + re-validated on
// the backend; this UI only gates and confirms. A customer can never be merged
// into itself (the loser is excluded from results and confirm stays disabled).

import { useState } from 'react'
import { ApiError } from '@/lib/api'
import { useCustomers, useMergeCustomer } from '@/hooks/useCustomers'
import type { Customer } from '@/types'

interface MergeCustomerModalProps {
  /** The customer being merged AWAY (the loser; the current detail page). */
  loser: Customer
  onClose: () => void
  /** Called after a successful merge with the surviving winner's id. */
  onMerged: (winnerId: number) => void
}

export function MergeCustomerModal({ loser, onClose, onMerged }: MergeCustomerModalProps) {
  const mutation = useMergeCustomer(loser.id)
  const [query, setQuery] = useState('')
  const [winner, setWinner] = useState<Customer | null>(null)
  const [error, setError] = useState<string | null>(null)

  const trimmed = query.trim()
  const active = trimmed.length >= 2
  // Only search while picking; never fetch q="" and never once a winner is chosen.
  const { data, isFetching } = useCustomers(
    { q: trimmed, limit: 8 },
    { enabled: active && winner === null },
  )
  // Exclude the loser itself — a customer can never be merged into itself.
  const results = active ? (data?.items ?? []).filter((c) => c.id !== loser.id) : []

  const canConfirm = winner !== null && winner.id !== loser.id && !mutation.isPending

  async function handleConfirm() {
    if (winner === null || winner.id === loser.id) return
    setError(null)
    try {
      await mutation.mutateAsync(winner.id)
      onMerged(winner.id)
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setError('You do not have permission to merge customers.')
      } else if (err instanceof ApiError && err.status === 404) {
        setError('One of these customers no longer exists.')
      } else if (err instanceof ApiError && err.status === 409) {
        setError('This merge is not allowed (a customer is already merged or no longer active).')
      } else if (err instanceof ApiError && err.status === 400) {
        setError('A customer cannot be merged into itself.')
      } else {
        setError('Merge failed. Please try again.')
      }
    }
  }

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/60 px-4"
      role="dialog"
      aria-modal="true"
      onClick={onClose}
    >
      <div
        className="card w-full max-w-lg p-6 shadow-2xl shadow-black/40"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="mb-1 text-lg font-semibold text-fg">Merge this customer into another</h2>
        <p className="mb-4 text-sm text-muted">
          <span className="text-fg">{loser.full_name}</span> (#{loser.id}) will be merged into the
          customer you choose, then hidden.
        </p>

        {error && (
          <div className="mb-4 rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
            {error}
          </div>
        )}

        {winner === null ? (
          <div>
            <label className="eyebrow mb-1 block text-faint">Keep this customer (the winner)</label>
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search by name / email / phone…"
              className="input w-full text-sm"
              autoFocus
            />
            {!active ? (
              <p className="mt-1 px-1 text-xs text-faint">Type at least 2 characters to search.</p>
            ) : (
              <ul className="mt-1 flex max-h-56 flex-col gap-1 overflow-y-auto">
                {isFetching && <li className="px-1 text-xs text-faint">Searching…</li>}
                {!isFetching && results.length === 0 && (
                  <li className="px-1 text-xs text-faint">No other customers found.</li>
                )}
                {results.map((c) => (
                  <li
                    key={c.id}
                    className="flex items-center justify-between gap-2 rounded border border-line px-2 py-1 text-sm"
                  >
                    <span className="min-w-0 truncate text-fg">
                      {c.full_name}
                      {c.suburb ? ` · ${c.suburb}` : ''}
                    </span>
                    <button
                      type="button"
                      onClick={() => setWinner(c)}
                      className="shrink-0 text-brand-400 hover:underline"
                    >
                      Select
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ) : (
          <div className="text-sm">
            <div className="rounded-md border border-line bg-elevated p-3">
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-faint">Hidden after merge</span>
                <span className="min-w-0 truncate text-fg">
                  {loser.full_name} (#{loser.id})
                </span>
              </div>
              <div className="mt-1 flex items-baseline justify-between gap-2">
                <span className="text-faint">Kept (winner)</span>
                <span className="min-w-0 truncate font-medium text-fg">
                  {winner.full_name} (#{winner.id})
                </span>
              </div>
              <button
                type="button"
                onClick={() => setWinner(null)}
                className="mt-2 text-xs text-brand-400 hover:underline"
              >
                Choose a different customer
              </button>
            </div>

            <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-amber-300">
              <li>The contact and address fields of the winner stay as-is and are NOT overwritten.</li>
              <li>
                Notes and internal notes from this customer are appended into the internal notes of
                the winner, under a merge header.
              </li>
              <li>
                All jobs, tasks, documents, timeline entries and import links move to the winner.
              </li>
              <li>This customer is hidden (soft-deleted) and marked as merged.</li>
              <li>
                <span className="font-medium">This cannot be undone in the app</span> — there is no
                unmerge yet.
              </li>
            </ul>
          </div>
        )}

        <div className="mt-6 flex justify-end gap-3">
          <button onClick={onClose} className="btn-secondary">
            Cancel
          </button>
          <button
            onClick={handleConfirm}
            disabled={!canConfirm}
            className="btn-primary disabled:opacity-50"
          >
            {mutation.isPending ? 'Merging…' : 'Merge'}
          </button>
        </div>
      </div>
    </div>
  )
}
