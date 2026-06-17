// Section B2-3 / B3-4 — same-customer resolution + pending-row grouping controls
// for the import row modal.
//
// A row is in exactly one state (the backend enforces this):
//   * unresolved / new        -> a new customer is created at commit;
//   * existing (B2)           -> attach the job to an existing live customer;
//   * group (B3)              -> this row + other pending rows become ONE future
//                                customer with multiple jobs (B3-3 commit).
// This section shows the current state as a banner and exposes the actions:
//   * B2: candidate "Use this customer", existing-customer search, Create new, Clear.
//   * B3: candidate "Group as same customer", a group banner with member list, and
//         set-primary / remove-this-row / dissolve controls.
// Editable only while the row is pending — locked rows render read-only.

import { useState } from 'react'
import { Link } from 'react-router-dom'

import { ApiError } from '@/lib/api'
import { useCustomer, useCustomers } from '@/hooks/useCustomers'
import {
  useAddGroupRow,
  useCreateCustomerGroup,
  useCustomerGroup,
  useDissolveCustomerGroup,
  useRemoveGroupRow,
  useResolveRowCustomer,
  useSetGroupPrimary,
} from '@/hooks/useImports'
import { MatchCandidatesPanel } from '@/components/imports/MatchCandidatesPanel'
import type {
  CustomerGroupRead,
  CustomerResolutionMode,
  CustomerResolutionRequest,
  ImportRow,
} from '@/types/imports'

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
  const createGroup = useCreateCustomerGroup(batchId)
  const addRow = useAddGroupRow(batchId)
  const removeRow = useRemoveGroupRow(batchId)
  const setPrimary = useSetGroupPrimary(batchId)
  const dissolve = useDissolveCustomerGroup(batchId)
  const [error, setError] = useState<string | null>(null)
  const [searchOpen, setSearchOpen] = useState(false)

  const mode = row.customer_resolution_mode
  const resolvedId = row.resolved_customer_id
  const groupId = row.customer_group_id
  const grouped = mode === 'group' && groupId != null
  // C (stabilization): committed rows have live records and reversed rows are
  // terminal — show a final / historical summary, never the active "possible same
  // customer" review controls. Active controls render only while `editable`
  // (the parent passes editable only for a pending row).
  const committed = row.review_status === 'committed'
  const reversed = row.review_status === 'reversed'
  const finalized = committed || reversed
  const busy =
    resolveMutation.isPending ||
    createGroup.isPending ||
    addRow.isPending ||
    removeRow.isPending ||
    setPrimary.isPending ||
    dissolve.isPending

  const { data: group } = useCustomerGroup(batchId, grouped ? groupId : null)
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

  // B3: group THIS row with an UNGROUPED pending candidate row. If this row is already
  // in a group, add the candidate to it; otherwise create a new group with this row as
  // the primary. (The backend hard-rejects an already-grouped candidate — use joinGroup.)
  async function groupWith(candidateRowId: number) {
    setError(null)
    try {
      if (groupId != null) {
        await addRow.mutateAsync({ groupId, rowId: candidateRowId })
      } else {
        await createGroup.mutateAsync({ primaryRowId: row.id, memberRowIds: [candidateRowId] })
      }
    } catch (err) {
      setError(describe(err, 'Could not group the rows.'))
    }
  }

  // B (stabilization): the candidate already belongs to a group — JOIN this row to that
  // existing group (preserving its primary) rather than stealing the candidate out.
  async function joinGroup(candidateGroupId: number) {
    setError(null)
    try {
      await addRow.mutateAsync({ groupId: candidateGroupId, rowId: row.id })
    } catch (err) {
      setError(describe(err, 'Could not join the group.'))
    }
  }

  async function groupAction(fn: () => Promise<unknown>, fallback: string) {
    setError(null)
    try {
      await fn()
    } catch (err) {
      setError(describe(err, fallback))
    }
  }

  // C: committed/reversed rows show a final / historical summary only.
  if (finalized) {
    return (
      <FinalizedResolutionSummary
        committed={committed}
        mode={mode}
        resolvedName={resolvedName}
        committedCustomerId={row.committed_customer_id}
        group={mode === 'group' ? (group ?? null) : null}
        currentRowId={row.id}
      />
    )
  }

  return (
    <section className="flex flex-col gap-2">
      {/* Current state banner */}
      {grouped ? (
        <GroupBanner
          group={group ?? null}
          currentRowId={row.id}
          editable={editable}
          busy={busy}
          onMakePrimary={() =>
            group && groupAction(() => setPrimary.mutateAsync({ groupId: group.id, primaryRowId: row.id }), 'Could not set the primary row.')
          }
          onRemoveSelf={() =>
            group && groupAction(() => removeRow.mutateAsync({ groupId: group.id, rowId: row.id }), 'Could not remove this row from the group.')
          }
          onDissolve={() =>
            group && groupAction(() => dissolve.mutateAsync({ groupId: group.id }), 'Could not dissolve the group.')
          }
        />
      ) : mode === 'existing' && resolvedId != null ? (
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
            No resolution set — a new customer will be created on commit. Use a candidate to
            attach to an existing customer or group with another pending row, search, or
            confirm a new one below.
          </p>
        )
      )}

      {/* Approved / rejected / skipped: resolution is read-only until reopened. */}
      {!editable && (
        <p className="text-xs text-faint">Reopen the row to change the customer resolution.</p>
      )}

      {error && <p className="text-xs text-red-300">{error}</p>}

      {/* Candidates — attach (B2) and group (B3) actions. Shown only while the row is
          review-editable (pending); committed/reversed render a final summary above,
          and an approved/closed row shows its chosen resolution read-only. */}
      {editable && (
        <MatchCandidatesPanel
          batchId={batchId}
          rowId={row.id}
          editable={editable}
          resolvedCustomerId={resolvedId}
          onUseCustomer={(customerId) => run({ mode: 'existing', customer_id: customerId })}
          onGroupWithRow={groupWith}
          onJoinGroup={joinGroup}
          groupMemberRowIds={group?.member_row_ids ?? []}
          busy={busy}
        />
      )}

      {/* Explicit B2 choices — hidden when this row is grouped. */}
      {editable && !grouped && (
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

      {editable && !grouped && searchOpen && (
        <CustomerSearch
          resolvedId={resolvedId}
          busy={busy}
          onPick={(customerId) => run({ mode: 'existing', customer_id: customerId })}
        />
      )}
    </section>
  )
}

// C/D: committed/reversed rows — a final / historical summary instead of the active
// "possible same customer" review controls. For a GROUPED finalized row it also shows
// a read-only group-status block (members, the current primary, per-member state, and
// the committed customer) so the reviewer can confirm continuity — e.g. that the
// primary was re-promoted after the original primary was reversed.
function FinalizedResolutionSummary({
  committed,
  mode,
  resolvedName,
  committedCustomerId,
  group,
  currentRowId,
}: {
  committed: boolean
  mode: CustomerResolutionMode | null
  resolvedName: string
  committedCustomerId: number | null
  group: CustomerGroupRead | null
  currentRowId: number
}) {
  // Grouped finalized row: show the group status (members + primary + committed customer).
  if (mode === 'group') {
    const groupCustomerId = group?.committed_customer_id ?? committedCustomerId
    const tone = committed
      ? 'border-emerald-500/30 bg-emerald-500/10'
      : 'border-line bg-elevated'
    const headText = committed ? 'text-emerald-200' : 'text-muted'
    return (
      <section className="flex flex-col gap-2">
        <div className={`rounded-md border px-3 py-2 ${tone}`}>
          <p className={`text-sm font-medium ${headText}`}>
            {committed ? '✓ Committed' : '↩ Reversed'} — customer group
          </p>
          {groupCustomerId != null && (
            <p className="mt-0.5 text-xs text-faint">
              Group customer:{' '}
              <Link to={`/customers/${groupCustomerId}`} className="text-brand-400 underline">
                {resolvedName || `#${groupCustomerId}`}
              </Link>
            </p>
          )}
          {group ? (
            <ul className="mt-1.5 flex flex-col gap-0.5">
              {group.members.map((m) => (
                <li key={m.row_id} className="flex flex-wrap items-center gap-x-2 text-xs">
                  <span className="text-faint">row #{m.source_row_index}</span>
                  <span className="text-fg">{m.customer_name || '(no name)'}</span>
                  {m.is_primary && (
                    <span className="rounded bg-indigo-500/25 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-indigo-200">
                      Primary
                    </span>
                  )}
                  <span className="text-[10px] uppercase tracking-wide text-faint">{m.review_status}</span>
                  {m.row_id === currentRowId && <span className="text-indigo-300/70">(this row)</span>}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-1 text-xs text-faint">Loading group…</p>
          )}
          <p className="mt-1 text-[11px] text-faint">
            The primary row owns the group's customer; if it was reversed the primary was
            re-promoted to the lowest-numbered remaining committed row. Read-only.
          </p>
        </div>
      </section>
    )
  }
  if (!committed) {
    return (
      <section className="flex flex-col gap-2">
        <div className="rounded-md border border-line bg-elevated px-3 py-2">
          <p className="text-sm font-medium text-muted">↩ Reversed</p>
          <p className="mt-0.5 text-xs text-faint">
            This import was reversed; its committed customer/job were soft-deleted. The
            customer resolution is historical and read-only.
          </p>
        </div>
      </section>
    )
  }
  const label = mode === 'existing' ? 'Attached to an existing customer' : 'New customer created'
  return (
    <section className="flex flex-col gap-2">
      <div className="rounded-md border border-emerald-500/30 bg-emerald-500/10 px-3 py-2">
        <p className="text-sm font-medium text-emerald-200">✓ Committed — {label}</p>
        {committedCustomerId != null && (
          <p className="mt-0.5 text-xs text-emerald-200/80">
            Customer:{' '}
            <Link to={`/customers/${committedCustomerId}`} className="underline">
              {resolvedName || `#${committedCustomerId}`}
            </Link>
          </p>
        )}
      </div>
    </section>
  )
}

function GroupBanner({
  group,
  currentRowId,
  editable,
  busy,
  onMakePrimary,
  onRemoveSelf,
  onDissolve,
}: {
  group: CustomerGroupRead | null
  currentRowId: number
  editable: boolean
  busy: boolean
  onMakePrimary: () => void
  onRemoveSelf: () => void
  onDissolve: () => void
}) {
  if (!group) {
    return (
      <div className="rounded-md border border-indigo-500/30 bg-indigo-500/10 px-3 py-2 text-sm text-indigo-200">
        Grouped as one future customer — loading members…
      </div>
    )
  }
  const isPrimary = currentRowId === group.primary_row_id
  return (
    <div className="rounded-md border border-indigo-500/30 bg-indigo-500/10 px-3 py-2">
      <p className="text-sm font-medium text-indigo-200">
        Grouped as one future customer ({group.members.length} rows)
      </p>
      <ul className="mt-1 flex flex-col gap-0.5">
        {group.members.map((m) => (
          <li key={m.row_id} className="flex flex-wrap items-center gap-x-2 text-xs text-indigo-100/90">
            <span className="text-indigo-200/60">row #{m.source_row_index}</span>
            <span className="text-fg">{m.customer_name || '(no name)'}</span>
            {m.is_primary && (
              <span className="rounded bg-indigo-500/25 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-indigo-200">
                Primary
              </span>
            )}
            {m.row_id === currentRowId && <span className="text-indigo-300/70">(this row)</span>}
          </li>
        ))}
      </ul>
      <p className="mt-1 text-[11px] text-indigo-200/60">
        On commit: the primary row creates the customer; the others attach a job to it.
      </p>
      {editable ? (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {!isPrimary && (
            <button
              type="button"
              onClick={onMakePrimary}
              disabled={busy}
              className="rounded border border-indigo-500/40 bg-indigo-500/10 px-2 py-0.5 text-xs font-medium text-indigo-200 hover:bg-indigo-500/20 disabled:opacity-50"
            >
              Set this row as primary
            </button>
          )}
          <button
            type="button"
            onClick={onRemoveSelf}
            disabled={busy}
            className="text-xs text-indigo-300 hover:underline disabled:opacity-50"
          >
            Remove this row from group
          </button>
          <button
            type="button"
            onClick={onDissolve}
            disabled={busy}
            className="text-xs text-indigo-300 hover:underline disabled:opacity-50"
          >
            Dissolve group
          </button>
        </div>
      ) : (
        <p className="mt-1 text-[11px] text-indigo-200/50">Locked — reopen the row to change the group.</p>
      )}
    </div>
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
  // G: only fetch once the 2-char minimum is met (no q="" fetch-and-discard).
  const { data, isFetching } = useCustomers({ q: trimmed, limit: 8 }, { enabled: active })
  const results = active ? (data?.items ?? []) : []

  return (
    <div className="rounded-md border border-line bg-elevated p-2">
      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search by name / email / phone…"
        className="input w-full text-sm"
      />
      {!active ? (
        <p className="mt-1 px-1 text-xs text-faint">Type at least 2 characters to search.</p>
      ) : (
        <ul className="mt-1 flex max-h-48 flex-col gap-1 overflow-y-auto">
          {isFetching && <li className="px-1 text-xs text-faint">Searching…</li>}
          {!isFetching && results.length === 0 && (
            <li className="px-1 text-xs text-faint">No customers found.</li>
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
