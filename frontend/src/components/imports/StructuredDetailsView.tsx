// Read-only structured view of a row's parsed.details (Phase 3b-1).
// Registry-driven: sections in registry order, individual labelled fields.
// Populated fields show by default; blank CORE fields are revealed per-section
// via a "show empty fields" toggle; blank legacy/import-only fields stay hidden.
// No editing here — 3b-2 adds structured edit/save. Dark SunCentral theme.

import { useState } from 'react'
import type { FieldRegistry, FieldSpec, ParsedDetails } from '@/types/imports'

function valueAtStorage(details: ParsedDetails, storage: string): unknown {
  if (!storage.startsWith('job.details.')) return undefined
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

function Section({ section, fields, details }: {
  section: { key: string; label: string }
  fields: FieldSpec[]
  details: ParsedDetails
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
      <dl className="grid grid-cols-1 gap-x-6 gap-y-1.5 sm:grid-cols-2">
        {visible.map(({ f, v }) => (
          <div key={f.key} className="flex flex-col">
            <dt className="text-xs text-faint">{f.label}</dt>
            <dd className={`break-words text-sm ${isBlank(v) ? 'text-faint' : 'text-fg'}`}>
              {display(v)}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

export function StructuredDetailsView({ registry, details }: {
  registry: FieldRegistry
  details: ParsedDetails
}) {
  const misfiled = details.notes?.misfiled ?? []
  const provenance = registry.fields.find((f) => f.key === 'provenance')
  const provText = provenance ? valueAtStorage(details, provenance.storage) : undefined

  return (
    <section className="flex flex-col gap-3">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">
        Structured details <span className="text-faint">(read-only)</span>
      </h3>

      {registry.sections.map((section) => {
        const fields = registry.fields.filter((f) => f.section === section.key && isValueField(f))
        if (fields.length === 0) return null
        return <Section key={section.key} section={section} fields={fields} details={details} />
      })}

      {/* Misfiled notes — diverted text preserved with its source column. */}
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
      {!isBlank(provText) && (
        <p className="text-xs text-faint">{display(provText)}</p>
      )}
    </section>
  )
}
