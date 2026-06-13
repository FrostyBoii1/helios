// Row detail drawer: raw cells (read-only), editable parsed candidate with
// original-vs-edited indication, issues list with resolve, and review actions.

import { useEffect, useMemo, useState } from 'react'
import { ApiError } from '@/lib/api'
import {
  useEditRow,
  useImportRow,
  useResolveIssue,
  useRowAction,
} from '@/hooks/useImports'
import type { RowAction } from '@/lib/imports'
import { ReviewStatusBadge, RowClassBadge } from '@/components/imports/ReviewStatusBadge'
import { SeverityChip } from '@/components/imports/IssueBadges'
import { CommitReverseSection } from '@/components/imports/CommitReverseSection'
import {
  PARSED_TEXT_FIELDS,
  type ImportRow,
  type ImportRowEdit,
  type ParsedCandidate,
  type PhoneEntry,
} from '@/types/imports'

interface ImportRowDrawerProps {
  batchId: number
  rowId: number
  onClose: () => void
}

function asString(value: unknown): string {
  if (value == null) return ''
  if (typeof value === 'string') return value
  return String(value)
}

function asEmails(parsed: ParsedCandidate | null): string[] {
  const v = parsed?.emails
  return Array.isArray(v) ? v.map(asString).filter(Boolean) : []
}

function asPhones(parsed: ParsedCandidate | null): PhoneEntry[] {
  const v = parsed?.phones
  if (!Array.isArray(v)) return []
  return v.map((p) => ({
    number: asString((p as PhoneEntry)?.number),
    label: asString((p as PhoneEntry)?.label),
  }))
}

export function ImportRowDrawer({ batchId, rowId, onClose }: ImportRowDrawerProps) {
  const { data: row, isLoading, isError } = useImportRow(batchId, rowId)

  return (
    <div
      className="fixed inset-0 z-20 flex justify-end bg-black/60"
      role="dialog"
      aria-modal="true"
      onClick={onClose}
    >
      <div
        className="flex h-full w-full max-w-xl flex-col overflow-y-auto border-l border-line bg-surface shadow-2xl shadow-black/40"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="sticky top-0 z-10 flex items-center justify-between border-b border-line bg-surface px-5 py-3">
          <h2 className="text-base font-semibold text-fg">
            {row?.legacy_reference || `Row ${row?.source_row_index ?? ''}`}
          </h2>
          <button
            onClick={onClose}
            className="rounded-md px-2 py-1 text-muted hover:bg-elevated hover:text-fg"
            aria-label="Close"
          >
            ✕
          </button>
        </header>

        {isLoading && <div className="p-5 text-sm text-muted">Loading row…</div>}
        {isError && (
          <div className="p-5 text-sm text-red-300">Could not load this row. Please try again.</div>
        )}
        {row && <DrawerBody batchId={batchId} row={row} />}
      </div>
    </div>
  )
}

function DrawerBody({ batchId, row }: { batchId: number; row: ImportRow }) {
  const editMutation = useEditRow(batchId)
  const actionMutation = useRowAction(batchId)
  const resolveMutation = useResolveIssue(batchId)

  const [text, setText] = useState<Record<string, string>>({})
  const [emails, setEmails] = useState<string[]>([])
  const [phones, setPhones] = useState<PhoneEntry[]>([])
  const [reviewNotes, setReviewNotes] = useState('')
  const [message, setMessage] = useState<{ kind: 'error' | 'success'; text: string } | null>(null)
  const [issueNotes, setIssueNotes] = useState<Record<number, string>>({})

  // (Re)initialise the form whenever the row data changes (e.g. after a save).
  useEffect(() => {
    const next: Record<string, string> = {}
    for (const { key } of PARSED_TEXT_FIELDS) next[key] = asString(row.parsed?.[key])
    setText(next)
    setEmails(asEmails(row.parsed))
    setPhones(asPhones(row.parsed))
    setReviewNotes(row.review_notes ?? '')
    setMessage(null)
  }, [row])

  const isApprovable = row.row_class === 'job' || row.row_class === 'ambiguous'
  const hasUnresolvedError = row.issues.some((i) => i.severity === 'error' && !i.resolved)
  const approveDisabledReason = !isApprovable
    ? 'Only job/ambiguous rows can be approved.'
    : hasUnresolvedError
      ? 'Resolve all error-severity issues before approving.'
      : null

  function buildEdit(): ImportRowEdit {
    const edit: ImportRowEdit = {}
    // PARSED_TEXT_FIELDS are all scalar string fields; assign through a string
    // view so the union with emails/phones doesn't widen the value type.
    const textEdit = edit as Record<string, string | null>
    for (const { key } of PARSED_TEXT_FIELDS) {
      const cur = text[key]?.trim() ?? ''
      const orig = asString(row.parsed?.[key]).trim()
      if (cur !== orig) textEdit[key] = cur === '' ? null : cur
    }
    const curEmails = emails.map((e) => e.trim()).filter(Boolean)
    if (JSON.stringify(curEmails) !== JSON.stringify(asEmails(row.parsed))) {
      edit.emails = curEmails
    }
    const curPhones = phones
      .map((p) => ({ number: p.number.trim(), label: p.label.trim() }))
      .filter((p) => p.number)
    if (JSON.stringify(curPhones) !== JSON.stringify(asPhones(row.parsed))) {
      edit.phones = curPhones
    }
    if (reviewNotes.trim() !== (row.review_notes ?? '').trim()) {
      edit.review_notes = reviewNotes.trim() || null
    }
    return edit
  }

  const pendingEdit = useMemo(buildEdit, [text, emails, phones, reviewNotes, row])
  const hasChanges = Object.keys(pendingEdit).length > 0

  async function handleSave() {
    setMessage(null)
    try {
      await editMutation.mutateAsync({ rowId: row.id, edit: pendingEdit })
      setMessage({ kind: 'success', text: 'Saved.' })
    } catch (err) {
      setMessage({ kind: 'error', text: describeError(err, 'Could not save the row.') })
    }
  }

  async function handleAction(action: RowAction) {
    setMessage(null)
    let notes: string | undefined
    if (action === 'reject' || action === 'skip') {
      const entered = window.prompt(`Optional note for ${action}:`, '')
      if (entered === null) return // cancelled
      notes = entered.trim() || undefined
    }
    try {
      await actionMutation.mutateAsync({ rowId: row.id, action, notes })
      setMessage({ kind: 'success', text: `Row ${action}${action === 'reopen' ? 'ed' : 'd'}.` })
    } catch (err) {
      setMessage({ kind: 'error', text: describeError(err, `Could not ${action} the row.`) })
    }
  }

  async function handleResolve(issueId: number) {
    setMessage(null)
    try {
      await resolveMutation.mutateAsync({ issueId, note: issueNotes[issueId]?.trim() || undefined })
      setMessage({ kind: 'success', text: 'Issue resolved.' })
    } catch (err) {
      setMessage({ kind: 'error', text: describeError(err, 'Could not resolve the issue.') })
    }
  }

  const busy =
    editMutation.isPending || actionMutation.isPending || resolveMutation.isPending
  // Committed rows have live records (C1); reversed rows are terminal (C3).
  // Both are locked: no edits or review actions.
  const committed = row.review_status === 'committed'
  const reversed = row.review_status === 'reversed'
  const locked = committed || reversed

  return (
    <div className="flex flex-1 flex-col gap-5 p-5">
      <div className="flex flex-wrap items-center gap-2">
        <RowClassBadge rowClass={row.row_class} />
        <ReviewStatusBadge status={row.review_status} />
        <span className="text-xs text-faint">Source row #{row.source_row_index}</span>
      </div>

      {message && (
        <div
          className={`rounded-md border px-3 py-2 text-sm ${
            message.kind === 'error'
              ? 'border-red-500/30 bg-red-500/10 text-red-300'
              : 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
          }`}
        >
          {message.text}
        </div>
      )}

      {/* Review actions — committed/reversed rows are locked (live records). */}
      {locked ? (
        <CommitReverseSection batchId={batchId} row={row} />
      ) : (
        <>
          <section className="flex flex-wrap gap-2">
            <button
              onClick={() => handleAction('approve')}
              disabled={busy || approveDisabledReason != null}
              title={approveDisabledReason ?? undefined}
              className="btn-primary disabled:opacity-50"
            >
              Approve
            </button>
            <button
              onClick={() => handleAction('reject')}
              disabled={busy}
              className="btn-secondary"
            >
              Reject
            </button>
            <button onClick={() => handleAction('skip')} disabled={busy} className="btn-secondary">
              Skip
            </button>
            <button onClick={() => handleAction('reopen')} disabled={busy} className="btn-secondary">
              Reopen
            </button>
          </section>
          {approveDisabledReason && (
            <p className="-mt-3 text-xs text-amber-300">{approveDisabledReason}</p>
          )}
        </>
      )}

      {/* Editable region — disabled wholesale once the row is committed. */}
      <fieldset disabled={locked} className="m-0 flex min-w-0 flex-col gap-5 border-0 p-0">
      {/* Issues */}
      <section>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">
          Issues ({row.issues.length})
        </h3>
        {row.issues.length === 0 ? (
          <p className="text-sm text-faint">No issues flagged.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {row.issues.map((issue) => (
              <li key={issue.id} className="rounded-md border border-line bg-elevated p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <SeverityChip severity={issue.severity} />
                  <span className="font-mono text-xs text-faint">{issue.kind}</span>
                  {issue.field && (
                    <span className="text-xs text-faint">· {issue.field}</span>
                  )}
                  {issue.resolved && (
                    <span className="ml-auto text-xs text-emerald-300">Resolved</span>
                  )}
                </div>
                <p className="mt-1 text-sm text-fg">{issue.message}</p>
                {issue.resolved ? (
                  issue.resolution_note && (
                    <p className="mt-1 text-xs text-muted">Note: {issue.resolution_note}</p>
                  )
                ) : (
                  <div className="mt-2 flex flex-col gap-2 sm:flex-row">
                    <input
                      value={issueNotes[issue.id] ?? ''}
                      onChange={(e) =>
                        setIssueNotes((prev) => ({ ...prev, [issue.id]: e.target.value }))
                      }
                      placeholder="Optional resolution note"
                      className="input flex-1"
                    />
                    <button
                      onClick={() => handleResolve(issue.id)}
                      disabled={busy}
                      className="btn-secondary whitespace-nowrap"
                    >
                      Resolve
                    </button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Parsed candidate (editable) */}
      <section>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">
          Parsed candidate
        </h3>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {PARSED_TEXT_FIELDS.map(({ key, label }) => {
            const original = row.original_parsed
              ? asString(row.original_parsed[key])
              : null
            const persisted = asString(row.parsed?.[key])
            const edited = original != null && original !== persisted
            return (
              <label key={key} className="block text-sm">
                <span className="mb-1 flex items-center gap-2 font-medium text-fg">
                  {label}
                  {edited && (
                    <span
                      className="rounded bg-brand-500/15 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-brand-300"
                      title={`Original: ${original || '(empty)'}`}
                    >
                      Edited
                    </span>
                  )}
                </span>
                <input
                  value={text[key] ?? ''}
                  onChange={(e) => setText((prev) => ({ ...prev, [key]: e.target.value }))}
                  className="input"
                />
                {edited && (
                  <span className="mt-1 block text-xs text-faint">
                    Original: {original || '(empty)'}
                  </span>
                )}
              </label>
            )
          })}
        </div>

        {/* Emails */}
        <label className="mt-3 block text-sm">
          <span className="mb-1 block font-medium text-fg">Emails (one per line)</span>
          <textarea
            value={emails.join('\n')}
            onChange={(e) => setEmails(e.target.value.split('\n'))}
            rows={2}
            className="input"
          />
        </label>

        {/* Phones */}
        <div className="mt-3">
          <span className="mb-1 block text-sm font-medium text-fg">Phones</span>
          <div className="flex flex-col gap-2">
            {phones.map((phone, idx) => (
              <div key={idx} className="flex gap-2">
                <input
                  value={phone.number}
                  onChange={(e) =>
                    setPhones((prev) =>
                      prev.map((p, i) => (i === idx ? { ...p, number: e.target.value } : p)),
                    )
                  }
                  placeholder="Number"
                  className="input flex-1"
                />
                <input
                  value={phone.label}
                  onChange={(e) =>
                    setPhones((prev) =>
                      prev.map((p, i) => (i === idx ? { ...p, label: e.target.value } : p)),
                    )
                  }
                  placeholder="Label"
                  className="input flex-1"
                />
                <button
                  onClick={() => setPhones((prev) => prev.filter((_, i) => i !== idx))}
                  className="btn-secondary"
                  aria-label="Remove phone"
                >
                  ✕
                </button>
              </div>
            ))}
            <button
              onClick={() => setPhones((prev) => [...prev, { number: '', label: '' }])}
              className="btn-secondary self-start"
            >
              + Add phone
            </button>
          </div>
        </div>

        {/* Review notes */}
        <label className="mt-3 block text-sm">
          <span className="mb-1 block font-medium text-fg">Review notes</span>
          <textarea
            value={reviewNotes}
            onChange={(e) => setReviewNotes(e.target.value)}
            rows={2}
            className="input"
          />
        </label>

        <div className="mt-4 flex justify-end">
          <button
            onClick={handleSave}
            disabled={busy || !hasChanges}
            className="btn-primary disabled:opacity-50"
          >
            {editMutation.isPending ? 'Saving…' : hasChanges ? 'Save changes' : 'No changes'}
          </button>
        </div>
      </section>
      </fieldset>

      {/* Raw cells (read-only) */}
      <section>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">
          Raw cells
        </h3>
        {row.raw && Object.keys(row.raw).length > 0 ? (
          <dl className="grid grid-cols-1 gap-x-4 gap-y-1 text-sm sm:grid-cols-[auto_1fr]">
            {Object.entries(row.raw).map(([key, value]) => (
              <div key={key} className="contents">
                <dt className="font-mono text-xs text-faint">{key}</dt>
                <dd className="break-words text-fg">{asString(value) || '—'}</dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className="text-sm text-faint">No raw cells.</p>
        )}
      </section>
    </div>
  )
}

function describeError(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    if (err.status === 403) return 'You do not have permission to do that.'
    if (err.status === 409 && typeof err.detail === 'string') return err.detail
    if (typeof err.detail === 'string') return err.detail
  }
  return fallback
}
