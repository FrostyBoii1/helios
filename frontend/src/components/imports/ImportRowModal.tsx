// Row detail modal (centered, two-column): structured details, raw cells, issues,
// and editable parsed candidate on the left; the "On commit" internal-notes preview
// + approval and the review actions on the (sticky) right. Converted from the prior
// side drawer.

import { useEffect, useMemo, useRef, useState } from 'react'
import { ApiError } from '@/lib/api'
import { previewInternalNotes } from '@/lib/internalNotesPreview'
import {
  useEditRow,
  useFieldRegistry,
  useImportRow,
  useResolveIssue,
  useRowAction,
} from '@/hooks/useImports'
import type { RowAction } from '@/lib/imports'
import { ReviewStatusBadge, RowClassBadge } from '@/components/imports/ReviewStatusBadge'
import { SeverityChip } from '@/components/imports/IssueBadges'
import { CommitReverseSection } from '@/components/imports/CommitReverseSection'
import { StructuredDetailsView, detailsPath } from '@/components/structured/StructuredDetailsView'
import { buildDetailsPatch } from '@/lib/detailsPatch'
import {
  PARSED_TEXT_FIELDS,
  type FieldSpec,
  type ImportRow,
  type ImportRowEdit,
  type ParsedCandidate,
  type ParsedDetails,
  type PhoneEntry,
} from '@/types/imports'

// Flat parsed-grid keys that are now owned by the structured details editor.
// Hidden from the flat grid when parsed.details is present (no duplicate editing).
// salesperson maps to the structured Sales Consultant (job.details.sales.salesperson_text).
const STRUCTURED_OWNED_FLAT_KEYS = new Set<string>([
  'salesperson',
  'no_of_panels',
  'panel_raw',
  'inverter_raw',
  'nmi_raw',
  'meter_no',
  'distributor_inferred',
  'retailer_raw',
  'install_day',
  'install_time',
  'installer_raw',
  'msb_state',
])

interface ImportRowModalProps {
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

export function ImportRowModal({ batchId, rowId, onClose }: ImportRowModalProps) {
  const { data: row, isLoading, isError } = useImportRow(batchId, rowId)
  const panelRef = useRef<HTMLDivElement>(null)

  // Accessibility: Escape closes; move focus into the modal on open. (No focus
  // trap — the app has no shared modal primitive for it; this is sane behavior.)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    panelRef.current?.focus()
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  // Centered modal: backdrop click closes (matching the previous drawer behavior);
  // the panel stops propagation. Large but not full-screen on desktop (max-w-5xl ≈
  // 1024px, max-h 90vh); near-fullscreen on small screens; content scrolls INSIDE
  // while the page behind stays fixed.
  return (
    <div
      className="fixed inset-0 z-30 flex items-center justify-center bg-black/60 p-3 sm:p-6"
      role="dialog"
      aria-modal="true"
      aria-label="Import row review"
      onClick={onClose}
    >
      <div
        ref={panelRef}
        tabIndex={-1}
        className="flex max-h-[90vh] w-full max-w-5xl flex-col overflow-hidden rounded-xl border border-line bg-surface shadow-2xl shadow-black/40 outline-none"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex shrink-0 items-start justify-between gap-3 border-b border-line bg-surface px-5 py-3">
          {/* Customer/client name is the prominent title when known; the legacy
              reference (e.g. "SC0242 - LL") stays visible as a subtitle. Falls
              back to the reference as the title when the name is missing. */}
          <div className="min-w-0">
            {asString(row?.parsed?.customer_name).trim() ? (
              <>
                <h2 className="truncate text-base font-semibold text-fg">
                  {asString(row?.parsed?.customer_name).trim()}
                </h2>
                <p className="truncate text-xs text-faint">
                  {row?.legacy_reference || `Row ${row?.source_row_index ?? ''}`}
                </p>
              </>
            ) : (
              <h2 className="truncate text-base font-semibold text-fg">
                {row?.legacy_reference || `Row ${row?.source_row_index ?? ''}`}
              </h2>
            )}
          </div>
          <button
            onClick={onClose}
            className="rounded-md px-2 py-1 text-muted hover:bg-elevated hover:text-fg"
            aria-label="Close"
          >
            ✕
          </button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto">
          {isLoading && <div className="p-5 text-sm text-muted">Loading row…</div>}
          {isError && (
            <div className="p-5 text-sm text-red-300">Could not load this row. Please try again.</div>
          )}
          {row && <ModalBody batchId={batchId} row={row} />}
        </div>
      </div>
    </div>
  )
}

function ModalBody({ batchId, row }: { batchId: number; row: ImportRow }) {
  const editMutation = useEditRow(batchId)
  const actionMutation = useRowAction(batchId)
  const resolveMutation = useResolveIssue(batchId)
  const { data: registry } = useFieldRegistry()
  // Phase 3b-1: structured read-only view when the row carries parsed.details.
  const details = row.parsed?.details ?? null
  // Land/legal parcel text stripped out of the Customer Name cell ("Lot 4 DP 588479")
  // is preserved in details.notes.misfiled under source_column "Customer Name".
  // Surface it right by the name fields so it is findable, not buried at the bottom.
  // (Distributor approval/reference phrases now live in details.notes.review_notes
  // and render in the neutral "Imported review notes" section, not here.)
  // Display-only; the canonical data still lives in details.notes.misfiled.
  const customerNameMisfiled = (details?.notes?.misfiled ?? []).filter(
    (m) => m.source_column === 'Customer Name',
  )
  // Exactly what import commit will seed into Job.internal_notes (read-only preview;
  // pre-commit editing of internal_notes is not supported yet — see the P5 report).
  const internalNotesPreview = previewInternalNotes(details)
  // Approval signal recorded by the parser (none/pending/approved). The "Needs
  // approval" auto-label is derived on the backend at commit, not projected here.
  const importApprovalState = asString(row.parsed?.approval_state).trim().toLowerCase() || 'none'

  const [text, setText] = useState<Record<string, string>>({})
  const [emails, setEmails] = useState<string[]>([])
  const [phones, setPhones] = useState<PhoneEntry[]>([])
  const [reviewNotes, setReviewNotes] = useState('')
  // Phase 3b-2: string UI state for structured fields, keyed by "<section>.<key>".
  const [detailsEdits, setDetailsEdits] = useState<Record<string, string>>({})
  const [message, setMessage] = useState<{ kind: 'error' | 'success'; text: string } | null>(null)
  const [issueNotes, setIssueNotes] = useState<Record<number, string>>({})

  // path ("<section>.<key>") → field spec, for input_type-aware coercion.
  const fieldByPath = useMemo(() => {
    const m = new Map<string, FieldSpec>()
    if (registry) for (const f of registry.fields) m.set(detailsPath(f.storage), f)
    return m
  }, [registry])

  // (Re)initialise the form whenever the row data changes (e.g. after a save).
  useEffect(() => {
    const next: Record<string, string> = {}
    for (const { key } of PARSED_TEXT_FIELDS) next[key] = asString(row.parsed?.[key])
    setText(next)
    setEmails(asEmails(row.parsed))
    setPhones(asPhones(row.parsed))
    setReviewNotes(row.review_notes ?? '')
    setDetailsEdits({})
    setMessage(null)
  }, [row])

  function handleDetailsChange(path: string, value: string) {
    setDetailsEdits((prev) => ({ ...prev, [path]: value }))
  }

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
    // Structured details patch — only touched-and-changed leaves, coerced.
    if (details) {
      const patch = buildDetailsPatch(detailsEdits, details, fieldByPath)
      if (patch) edit.details = patch
    }
    return edit
  }

  const pendingEdit = useMemo(buildEdit, [text, emails, phones, reviewNotes, detailsEdits, fieldByPath, details, row])
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
  // An already-approved row shows a neutral "Approved" state instead of a
  // clickable Approve button (re-clicking is harmless but confusing).
  const approved = row.review_status === 'approved'

  // Name-cell notes get a dedicated (de-emphasized) edit field below — the primary
  // read-only display is the "On commit" internal-notes preview; compute edited state.
  const nameNotesOriginal = row.original_parsed
    ? asString(row.original_parsed['customer_name_notes'])
    : null
  const nameNotesEdited =
    nameNotesOriginal != null &&
    nameNotesOriginal !== asString(row.parsed?.['customer_name_notes'])

  return (
    <div className="flex flex-col gap-4 p-5">
      <div className="flex flex-wrap items-center gap-2">
        <RowClassBadge rowClass={row.row_class} />
        <ReviewStatusBadge status={row.review_status} />
        <span className="text-xs text-faint">Source row #{row.source_row_index}</span>
      </div>

      {/* Operationally important: old-system removal / decommission flag. */}
      {row.parsed?.removes_old_system && (
        <div className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2">
          <p className="text-sm font-semibold text-amber-300">⚠ Remove old system / decommission</p>
          <p className="mt-0.5 text-xs text-amber-200/80">
            Detected in the import
            {asString(row.parsed?.decommission_marker)
              ? ` (matched: “${asString(row.parsed?.decommission_marker)}”)`
              : ''}
            . Confirm and plan the old-system removal.
          </p>
        </div>
      )}

      {/* Two-column review layout: main review content (structured details, issues,
          parsed fields, raw cells) on the left; the commit outcome — internal-notes
          preview + approval — and the review actions on the right, like the Job
          detail page. Stacks vertically on small screens. */}
      <div className="grid grid-cols-1 items-start gap-5 lg:grid-cols-3">
        <div className="min-w-0 lg:col-span-2 lg:col-start-1 lg:row-start-1">
      {/* Phase 3b-1: registry-driven structured read-only view. Falls back to the
          flat fields below (with a hint) for rows staged before structured parsing. */}
      {details && registry ? (
        <StructuredDetailsView
          registry={registry}
          details={details}
          editable={!locked}
          edits={detailsEdits}
          onChange={handleDetailsChange}
          originalDetails={(row.original_parsed?.details as ParsedDetails | null) ?? null}
        />
      ) : (
        <div className="rounded-md border border-dashed border-line-strong bg-surface px-3 py-2">
          <p className="text-xs text-faint">
            Structured view available after re-ingest — showing the legacy fields below.
          </p>
        </div>
      )}
        </div>

        <aside className="flex min-w-0 flex-col gap-4 lg:sticky lg:top-0 lg:col-start-3 lg:row-span-2 lg:row-start-1 lg:self-start">
      {/* What this row will become on commit: the approval signal recorded by the
          import, and the EXACT text that will be seeded into Job.internal_notes.
          Read-only preview (direct internal_notes editing isn't supported yet —
          adjust "Name-cell notes" / structured fields below to change it). */}
      {(row.row_class === 'job' || row.row_class === 'ambiguous') && (
        <section className="rounded-md border border-line bg-elevated p-3">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">On commit</h3>
            <span className="inline-flex items-center gap-1.5 text-xs text-faint">
              Approval (from import):
              <span className="font-medium capitalize text-fg">{importApprovalState}</span>
            </span>
          </div>
          <p className="mb-1 text-xs text-faint">Will be saved as Job internal notes:</p>
          {internalNotesPreview ? (
            <div className="max-h-40 overflow-y-auto whitespace-pre-wrap break-words rounded border border-line bg-surface px-3 py-2 text-sm text-fg/90">
              {internalNotesPreview}
            </div>
          ) : (
            <p className="rounded border border-dashed border-line-strong bg-surface px-3 py-2 text-sm text-faint">
              No internal notes — nothing extra was preserved for this row.
            </p>
          )}
          <p className="mt-1.5 text-xs text-faint">
            Read-only preview. Editing internal notes before commit isn’t supported yet.
          </p>
        </section>
      )}

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
          <section className="flex flex-wrap items-center gap-2">
            {approved ? (
              <span className="inline-flex items-center gap-1 rounded-md border border-emerald-500/30 bg-emerald-500/10 px-3 py-1.5 text-sm font-medium text-emerald-300">
                ✓ Approved
              </span>
            ) : (
              <button
                onClick={() => handleAction('approve')}
                disabled={busy || approveDisabledReason != null}
                title={approveDisabledReason ?? undefined}
                className="btn-primary disabled:opacity-50"
              >
                Approve
              </button>
            )}
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
          {!approved && approveDisabledReason && (
            <p className="-mt-3 text-xs text-amber-300">{approveDisabledReason}</p>
          )}
        </>
      )}
        </aside>

        <div className="flex min-w-0 flex-col gap-5 lg:col-span-2 lg:col-start-1 lg:row-start-2">
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

        {/* Name-cell notes — the EDITABLE source for preserved Customer Name text.
            De-emphasized (no longer a prominent card): the read-only "On commit"
            internal-notes preview on the right is the primary display. Kept editable
            because it is currently the only way to change what import commit seeds
            into Job.internal_notes. */}
        <label className="mb-3 block text-sm">
          <span className="mb-1 flex items-center gap-2 font-medium text-fg">
            Name-cell notes
            {nameNotesEdited && (
              <span
                className="rounded bg-brand-500/15 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-brand-300"
                title={`Original: ${nameNotesOriginal || '(empty)'}`}
              >
                Edited
              </span>
            )}
          </span>
          <textarea
            value={text['customer_name_notes'] ?? ''}
            onChange={(e) =>
              setText((prev) => ({ ...prev, customer_name_notes: e.target.value }))
            }
            rows={2}
            placeholder="Extra text preserved from the Customer Name cell"
            className="input"
          />
          <span className="mt-1 block text-xs text-faint">
            Editable — feeds the “On commit” internal-notes preview.
          </span>
        </label>

        {/* Land/legal parcel text stripped off the Customer Name cell, surfaced
            read-only right by the name — the same entries also appear in the
            "Imported source notes" list below. Neutral (preserved source text, not
            an error). Never written back into customer_name. */}
        {customerNameMisfiled.length > 0 && (
          <div className="mb-3 rounded-md border border-line bg-elevated p-3">
            <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">
              Removed from customer name
            </h4>
            <p className="mb-1.5 text-xs text-faint">
              Stripped from the Customer Name cell and preserved as imported source text (read-only).
            </p>
            <ul className="flex flex-col gap-1">
              {customerNameMisfiled.map((m, i) => (
                <li key={i} className="break-words text-sm text-fg/90">
                  {m.text ?? ''}
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {PARSED_TEXT_FIELDS.filter(
            (f) =>
              f.key !== 'customer_name_notes' &&
              !(details && STRUCTURED_OWNED_FLAT_KEYS.has(f.key)),
          ).map(({ key, label }) => {
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
      </div>
    </div>
  )
}

function describeError(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    if (err.status === 403) return 'You do not have permission to do that.'
    if (err.status === 409 && typeof err.detail === 'string') return err.detail
    if (err.status === 422) {
      return typeof err.detail === 'string'
        ? err.detail
        : 'Some structured fields could not be saved (disallowed path or invalid value).'
    }
    if (typeof err.detail === 'string') return err.detail
  }
  return fallback
}
