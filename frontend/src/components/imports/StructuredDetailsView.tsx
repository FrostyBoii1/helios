// Structured view of a row's parsed.details (Phase 3b). Dual-mode:
//  - read-only by default (display values);
//  - editable when `editable` + `edits`/`onChange` are passed (registry-driven
//    inputs by input_type). Misfiled/flag/readonly stay read-only either way.
// Registry-driven: sections in registry order; populated fields show by default;
// blank CORE fields are revealed per-section via a "show empty fields" toggle;
// blank legacy/import-only fields stay hidden. Dark SunCentral theme.

import { useState } from 'react'
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

function Section({ section, fields, details, edit }: {
  section: { key: string; label: string }
  fields: FieldSpec[]
  details: ParsedDetails
  edit: EditCtx | null
}) {
  const [showEmpty, setShowEmpty] = useState(false)
  const rows = fields.map((f) => ({ f, v: valueAtStorage(details, f.storage) }))
  const populated = rows.filter((r) => !isBlank(r.v))
  // Blank CORE fields are revealable; blank legacy fields are always hidden.
  const blankCore = rows.filter((r) => isBlank(r.v) && r.f.category === 'core')
  const visible = showEmpty ? [...populated, ...blankCore] : populated

  if (populated.length === 0 && blankCore.length === 0) return null

  return (
    <div className="rounded-md border border-line bg-elevated p-3">
      <div className="mb-2 flex items-center justify-between">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-muted">
          {section.label} <span className="text-faint">· {populated.length} set</span>
        </h4>
        {blankCore.length > 0 && (
          <button
            onClick={() => setShowEmpty((s) => !s)}
            className="text-xs text-brand-400 underline hover:text-brand-500"
          >
            {showEmpty ? 'Hide empty' : `Show ${blankCore.length} empty`}
          </button>
        )}
      </div>
      <div className="grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2">
        {visible.map(({ f, v }) => {
          // Edited marker: original_parsed.details vs current parsed.details.
          const orig = edit?.originalDetails ? valueAtStorage(edit.originalDetails, f.storage) : undefined
          const edited = edit?.originalDetails != null && toStr(orig) !== toStr(v)
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
  const misfiled = details.notes?.misfiled ?? []
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
        return <Section key={section.key} section={section} fields={fields} details={details} edit={edit} />
      })}

      {/* Misfiled notes — diverted text preserved with its source column (read-only). */}
      {misfiled.length > 0 && (
        <div className="rounded-md border border-amber-500/30 bg-amber-500/10 p-3">
          <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-amber-300">
            Imported notes (misfiled)
          </h4>
          <ul className="flex flex-col gap-1">
            {misfiled.map((m, i) => (
              <li key={i} className="text-sm text-amber-100/90">
                {m.source_column ? (
                  <span className="text-amber-300/80">from {m.source_column}: </span>
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
