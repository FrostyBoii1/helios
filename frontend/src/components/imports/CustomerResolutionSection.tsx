// Section B2-3 — same-customer resolution controls for the import row modal.
//
// Lets a reviewer record (before approval) whether this row should create a NEW
// customer or ATTACH its job to an EXISTING live customer. Shows the current
// resolution as a banner, exposes the advisory match candidates as actionable
// "Use this customer" picks, a small existing-customer search, an explicit
// "Create new customer", and "Clear resolution". Storage/commit/preview/reverse
// behaviour all live in the backend (B2-1/B2-2); this is purely the UI.
//
// Editable only while the row is pending — once approved/committed/reversed the
// backend locks it, so we render the current state read-only and hide the controls.

import { useState } from 'react'
import { Link } from 'react-router-dom'

import { ApiError } from '@/lib/api'
import { useCustomer, useCustomers } from '@/hooks/useCustomers'
import { useResolveRowCustomer } from '@/hooks/useImports'
import { MatchCandidatesPanel } from '@/components/imports/MatchCandidatesPanel'
import type { CustomerResolutionRequest, ImportRow } from '@/types/imports'

interface Props {
  batchId: number
  row: ImportRow
  editable: boolean
}

function describe(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    if (err.status === 403) return 'You do not have permission to do that.'
    if (typeof err.detail === 'string') return err.detail
  }
  return fallback
}

export function CustomerResolutionSection({ batchId, row, editable }: Props) {
  const resolveMutation = useResolveRowCustomer(batchId)
  const [error, setError] = useState<string | null>(null)
  const [searchOpen, setSearchOpen] = useState(false)

  const mode = row.customer_resolution_mode
  const resolvedId = row.resolved_customer_id
  const busy = resolveMutation.isPending

  // Resolve the existing-customer's name for the banner (skips when unresolved).
  const { data: resolvedCustomer } = useCustomer(resolvedId ?? 0)
  const resolvedName = resolvedCustomer?.full_name ?? (resolvedId != null ? `#${resolvedId}` : '')

  async function run(payload: CustomerResolutionRequest) {
    setError(null)
    try {
      await resolveMutation.mutateAsync({ rowId: row.id, payload })
    } catch (err) {
      setError(describe(err, 'Could not update the customer resolution.'))
    }
  }

  return (
    <section className="flex flex-col gap-2">
      {/* Current resolution banner */}
      {mode === 'existing' && resolvedId != null ? (
        <div className="rounded-md border border-emerald-500/30 bg-emerald-500/10 px-3 py-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm font-medium text-emerald-200">
              Will attach this job to existing customer:{' '}
              <Link to={`/customers/${resolvedId}`} className="underline">
                {resolvedName}
              </Link>
            </p>
            {editable && (
              <button
                type="button"
                onClick={() => run({ mode: 'clear' })}
                disabled={busy}
                className="text-xs text-emerald-300 hover:underline disabled:opacity-50"
              >
                Clear resolution
              </button>
            )}
          </div>
          {row.customer_resolution_reason && (
            <p className="mt-0.5 text-xs text-emerald-200/70">{row.customer_resolution_reason}</p>
          )}
        </div>
      ) : mode === 'new' ? (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-sky-500/30 bg-sky-500/10 px-3 py-2">
          <p className="text-sm font-medium text-sky-200">Will create a new customer.</p>
          {editable && (
            <button
              type="button"
              onClick={() => run({ mode: 'clear' })}
              disabled={busy}
              className="text-xs text-sky-300 hover:underline disabled:opacity-50"
            >
              Clear resolution
            </button>
          )}
        </div>
      ) : (
        editable && (
          <p className="text-xs text-faint">
            No resolution set — a new customer will be created on commit. Pick a candidate,
            search for an existing customer, or confirm a new one below.
          </p>
        )
      )}

      {error && <p className="text-xs text-red-300">{error}</p>}

      {/* Advisory candidates, made actionable on an editable row. */}
      <MatchCandidatesPanel
        batchId={batchId}
        rowId={row.id}
        editable={editable}
        resolvedCustomerId={resolvedId}
        onUseCustomer={(customerId) => run({ mode: 'existing', customer_id: customerId })}
        busy={busy}
      />

      {/* Explicit choices (pending rows only). */}
      {editable && (
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => run({ mode: 'new' })}
            disabled={busy || mode === 'new'}
            className="btn-secondary text-xs disabled:opacity-50"
          >
            Create new customer
          </button>
          <button
            type="button"
            onClick={() => setSearchOpen((o) => !o)}
            disabled={busy}
            className="btn-secondary text-xs disabled:opacity-50"
          >
            {searchOpen ? 'Hide search' : 'Search existing customers…'}
          </button>
        </div>
      )}

      {editable && searchOpen && (
        <CustomerSearch
          resolvedId={resolvedId}
          busy={busy}
          onPick={(customerId) => run({ mode: 'existing', customer_id: customerId })}
        />
      )}
    </section>
  )
}

function CustomerSearch({
  resolvedId,
  busy,
  onPick,
}: {
  resolvedId: number | null
  busy: boolean
  onPick: (customerId: number) => void
}) {
  const [query, setQuery] = useState('')
  const trimmed = query.trim()
  const active = trimmed.length >= 2
  const { data, isFetching } = useCustomers({ q: active ? trimmed : '', limit: 8 })
  const results = active ? (data?.items ?? []) : []

  return (
    <div className="rounded-md border border-line bg-elevated p-2">
      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search by name / email / phone…"
        className="input w-full text-sm"
      />
      {active && (
        <ul className="mt-1 flex max-h-48 flex-col gap-1 overflow-y-auto">
          {isFetching && <li className="px-1 text-xs text-faint">Searching…</li>}
          {!isFetching && results.length === 0 && (
            <li className="px-1 text-xs text-faint">No matches.</li>
          )}
          {results.map((c) => (
            <li
              key={c.id}
              className="flex items-center justify-between gap-2 rounded border border-line px-2 py-1 text-xs"
            >
              <span className="min-w-0 truncate text-fg">
                {c.full_name}
                {c.suburb ? ` · ${c.suburb}` : ''}
              </span>
              {c.id === resolvedId ? (
                <span className="shrink-0 text-emerald-300">Selected ✓</span>
              ) : (
                <button
                  type="button"
                  onClick={() => onPick(c.id)}
                  disabled={busy}
                  className="shrink-0 text-brand-400 hover:underline disabled:opacity-50"
                >
                  Use
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
