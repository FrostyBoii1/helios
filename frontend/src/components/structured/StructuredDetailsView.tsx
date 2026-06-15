// Shared structured view of a registry-shaped details object (Phase 3b/4).
// Used by the import review drawer (row.parsed.details) and the live Job detail
// page (job.details) — both carry the same registry shape. Dual-mode:
//  - read-only by default (display values);
//  - editable when `editable` + `edits`/`onChange` are passed (registry-driven
//    inputs by input_type). Misfiled/flag/readonly stay read-only either way.
// Registry-driven: sections in registry order; populated fields show by default;
// blank CORE fields are revealed per-section via a "show empty fields" toggle;
// blank legacy/import-only fields stay hidden. Dark SunCentral theme.

import { useEffect, useState } from 'react'
import type { FieldRegistry, FieldSpec, ParsedDetails } from '@/types/imports'

/** "<section>.<key>" path for a job.details.* storage path. */
export function detailsPath(storage: string): string {
  return storage.startsWith('job.details.') ? storage.slice('job.details.'.length) : storage
}

function valueAtStorage(details: ParsedDetails | null | undefined, storage: string): unknown {
  if (!details || !storage.startsWith('job.details.')) return undefined
  const parts = storage.slice('job.details.'.length).split('.')
  let cur: unknown = details
  for (const p of parts) {
    if (cur == null || typeof cur !== 'object') return undefined
    cur = (cur as Record<string, unknown>)[p]
  }
  return cur
}

function isBlank(v: unknown): boolean {
  return v == null || v === '' || (Array.isArray(v) && v.length === 0)
}

function toStr(v: unknown): string {
  if (v == null) return ''
  if (typeof v === 'boolean') return v ? 'true' : 'false'
  return String(v)
}

function display(v: unknown): string {
  if (v == null) return '—'
  if (typeof v === 'boolean') return v ? 'Yes' : 'No'
  return String(v)
}

// Structured value fields only (exclude derived flag/readonly + the misfiled list).
function isValueField(f: FieldSpec): boolean {
  return (
    f.storage.startsWith('job.details.') &&
    f.input_type !== 'flag' &&
    f.input_type !== 'readonly' &&
    f.key !== 'misfiled_notes'
  )
}

interface EditCtx {
  edits: Record<string, string>
  onChange: (path: string, value: string) => void
  originalDetails: ParsedDetails | null
}

function FieldInput({ field, details, edit }: { field: FieldSpec; details: ParsedDetails; edit: EditCtx }) {
  const path = detailsPath(field.storage)
  const current = edit.edits[path] ?? toStr(valueAtStorage(details, field.storage))
  const set = (v: string) => edit.onChange(path, v)
  const rawOpts = field.validation?.select_options
  const opts = Array.isArray(rawOpts) ? rawOpts.map(String) : null

  if (field.input_type === 'textarea') {
    return <textarea rows={2} value={current} onChange={(e) => set(e.target.value)} className="input" />
  }
  if (field.input_type === 'select' && opts) {
    return (
      <select value={current} onChange={(e) => set(e.target.value)} className="input">
        <option value="">—</option>
        {opts.map((o) => (
          <option key={o} value={o}>{o}</option>
        ))}
      </select>
    )
  }
  const type = field.input_type === 'number' ? 'number' : field.input_type === 'date' ? 'date' : 'text'
  return <input type={type} value={current} onChange={(e) => set(e.target.value)} className="input" />
}

function Section({ section, fields, details, edit, expanded, onToggle, addedPaths, onRemoveAdded }: {
  section: { key: string; label: string }
  fields: FieldSpec[]
  details: ParsedDetails
  edit: EditCtx | null
  expanded: boolean
  onToggle: () => void
  addedPaths: Set<string>
  onRemoveAdded: (path: string) => void
}) {
  const rows = fields.map((f) => ({ f, v: valueAtStorage(details, f.storage), path: detailsPath(f.storage) }))
  const populated = rows.filter((r) => !isBlank(r.v))
  // Blank CORE fields are revealable via the per-section show-empty toggle.
  const blankCore = rows.filter((r) => isBlank(r.v) && r.f.category === 'core')
  // Blank fields explicitly added via the picker (any category, incl. legacy).
  const addedRows = rows.filter((r) => isBlank(r.v) && addedPaths.has(r.path))

  // A field can qualify under more than one bucket — dedupe by key, preserve order.
  const visibleMap = new Map<string, (typeof rows)[number]>()
  for (const r of populated) visibleMap.set(r.f.key, r)
  if (expanded) for (const r of blankCore) visibleMap.set(r.f.key, r)
  for (const r of addedRows) visibleMap.set(r.f.key, r)
  const visible = [...visibleMap.values()]

  if (visible.length === 0) return null

  return (
    <div className="rounded-md border border-line bg-elevated p-3">
      <div className="mb-2 flex items-center justify-between">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-muted">
          {section.label} <span className="text-faint">· {populated.length} set</span>
        </h4>
        {blankCore.length > 0 && (
          <button
            onClick={onToggle}
            className="text-xs text-brand-400 underline hover:text-brand-500"
          >
            {expanded ? 'Hide empty' : `Show ${blankCore.length} empty`}
          </button>
        )}
      </div>
      <div className="grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2">
        {visible.map(({ f, v, path }) => {
          // Edited marker: original_parsed.details vs current parsed.details.
          const orig = edit?.originalDetails ? valueAtStorage(edit.originalDetails, f.storage) : undefined
          const edited = edit?.originalDetails != null && toStr(orig) !== toStr(v)
          // A locally-added field with no saved value gets a remove control (it
          // only hides the local addition + clears its unsaved edit — never a
          // persisted value).
          const isAddedBlank = edit != null && addedPaths.has(path) && isBlank(v)
          return (
            <div key={f.key} className="flex min-w-0 flex-col">
              <span className="mb-0.5 flex items-center gap-1.5 text-xs text-faint">
                {f.label}
                {edited && (
                  <span
                    className="rounded bg-brand-500/15 px-1 py-0.5 text-[10px] font-medium uppercase tracking-wide text-brand-300"
                    title={`Original: ${display(orig) || '(empty)'}`}
                  >
                    Edited
                  </span>
                )}
                {isAddedBlank && (
                  <button
                    type="button"
                    onClick={() => onRemoveAdded(path)}
                    className="ml-auto rounded px-1 leading-none text-faint hover:text-red-300"
                    title="Remove this added field"
                    aria-label={`Remove ${f.label}`}
                  >
                    ✕
                  </button>
                )}
              </span>
              {edit ? (
                <FieldInput field={f} details={details} edit={edit} />
              ) : (
                <span className={`break-words text-sm ${isBlank(v) ? 'text-faint' : 'text-fg'}`}>
                  {display(v)}
                </span>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

export function StructuredDetailsView({ registry, details, editable, edits, onChange, originalDetails }: {
  registry: FieldRegistry
  details: ParsedDetails
  editable?: boolean
  edits?: Record<string, string>
  onChange?: (path: string, value: string) => void
  originalDetails?: ParsedDetails | null
}) {
  const edit: EditCtx | null =
    editable && edits && onChange ? { edits, onChange, originalDetails: originalDetails ?? null } : null

  // Per-section show-empty expansion + picker-added field paths. Both are local
  // reveal state — they never persist, and reset when the record changes (a new
  // row/job, or a post-save refetch hands us a fresh `details` object).
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [addedPaths, setAddedPaths] = useState<Set<string>>(new Set())
  useEffect(() => {
    setExpanded(new Set())
    setAddedPaths(new Set())
  }, [details])

  const toggleSection = (key: string) =>
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  const addPath = (path: string) => setAddedPaths((prev) => new Set(prev).add(path))
  const removeAdded = (path: string) => {
    setAddedPaths((prev) => {
      const next = new Set(prev)
      next.delete(path)
      return next
    })
    onChange?.(path, '') // clear any unsaved local edit; never touches saved values
  }

  // Picker options (editable only): blank, editable job.details fields that are
  // not already visible — i.e. not populated, not added, and not a blank-core
  // field already revealed by show-empty. Grouped by section.
  const addableBySection = registry.sections
    .map((s) => ({
      section: s,
      fields: registry.fields.filter(
        (f) =>
          f.section === s.key &&
          isValueField(f) &&
          isBlank(valueAtStorage(details, f.storage)) &&
          !addedPaths.has(detailsPath(f.storage)) &&
          !(f.category === 'core' && expanded.has(f.section)),
      ),
    }))
    .filter((g) => g.fields.length > 0)

  const misfiled = details.notes?.misfiled ?? []
  const reviewNotes = details.notes?.review_notes ?? []
  const provenance = registry.fields.find((f) => f.key === 'provenance')
  const provText = provenance ? valueAtStorage(details, provenance.storage) : undefined

  return (
    <section className="flex flex-col gap-3">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">
        Structured details {edit ? null : <span className="text-faint">(read-only)</span>}
      </h3>

      {registry.sections.map((section) => {
        const fields = registry.fields.filter((f) => f.section === section.key && isValueField(f))
        if (fields.length === 0) return null
        return (
          <Section
            key={section.key}
            section={section}
            fields={fields}
            details={details}
            edit={edit}
            expanded={expanded.has(section.key)}
            onToggle={() => toggleSection(section.key)}
            addedPaths={addedPaths}
            onRemoveAdded={removeAdded}
          />
        )
      })}

      {/* Add-field picker (editable only): reveal a blank/hidden registry field —
          incl. legacy/import-only fields that show-empty never surfaces. Local
          reveal only; nothing persists until the user enters a value and saves. */}
      {edit && addableBySection.length > 0 && (
        <div className="flex items-center gap-2">
          <label htmlFor="add-structured-field" className="text-xs text-faint">
            Add field
          </label>
          <select
            id="add-structured-field"
            value=""
            onChange={(e) => {
              if (e.target.value) addPath(e.target.value)
            }}
            className="input max-w-xs text-sm"
          >
            <option value="">Add a field…</option>
            {addableBySection.map((g) => (
              <optgroup key={g.section.key} label={g.section.label}>
                {g.fields.map((f) => (
                  <option key={f.key} value={detailsPath(f.storage)}>
                    {f.label}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        </div>
      )}

      {/* Imported review notes — recognized context (distributor approval/reference
          phrases, a sales-cell DOB/panel remainder) preserved with its source
          column. Neutral, NOT a warning: the data is fine, it just couldn't be
          auto-structured. Genuine problems surface as ImportIssues, not here. */}
      {reviewNotes.length > 0 && (
        <div className="rounded-md border border-line bg-elevated p-3">
          <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted">
            Imported review notes
          </h4>
          <ul className="flex flex-col gap-1">
            {reviewNotes.map((m, i) => (
              <li key={i} className="text-sm text-fg/90">
                {m.source_column ? (
                  <span className="text-faint">from {m.source_column}: </span>
                ) : null}
                <span className="break-words">{m.text ?? ''}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Imported source notes — other leftover column text preserved with its
          source column (read-only). Neutral: preserved source text is not an
          error. */}
      {misfiled.length > 0 && (
        <div className="rounded-md border border-line bg-elevated p-3">
          <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted">
            Imported source notes
          </h4>
          <ul className="flex flex-col gap-1">
            {misfiled.map((m, i) => (
              <li key={i} className="text-sm text-fg/90">
                {m.source_column ? (
                  <span className="text-faint">from {m.source_column}: </span>
                ) : null}
                <span className="break-words">{m.text ?? ''}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Provenance (read-only). */}
      {!isBlank(provText) && <p className="text-xs text-faint">{display(provText)}</p>}
    </section>
  )
}
