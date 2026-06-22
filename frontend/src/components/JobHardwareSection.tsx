// Job Detail > Hardware (Hardware Parser lane, Stage 3B).
//
// Reads + edits the Job-owned hardware SNAPSHOT at Job.details.hardware (created in Stage 3A).
// This is a stored snapshot, NOT a live catalogue reference: it never reads hardware_catalogue,
// uses no catalogue dropdowns, and does not update when Settings > Hardware changes. Saving sends
// the whole hardware object through the existing Job details PATCH (`{ details: { hardware } }`),
// which the backend validates by shape and merges without touching other Job details.
//
// details=null jobs can't be structured-edited (the backend 422s), so the section shows a clear
// read-only note instead of attempting to initialise details.

import { useState } from 'react'
import type { ReactNode } from 'react'
import { ApiError } from '@/lib/api'
import { useAuth } from '@/auth/AuthContext'
import { canEditJobDetails } from '@/auth/permissions'
import { useUpdateJob } from '@/hooks/useJobs'
import type { Job } from '@/types'
import type {
  JobHardwareItem,
  JobHardwarePanel,
  JobHardwareSiteNotes,
  JobHardwareSnapshot,
} from '@/types/imports'

const SNAPSHOT_NOTE =
  'Editable job snapshot — does not update from Settings > Hardware.'

type ItemKind = 'inverters' | 'batteries' | 'metering'
const ITEM_KINDS: { key: ItemKind; label: string }[] = [
  { key: 'inverters', label: 'Inverters' },
  { key: 'batteries', label: 'Batteries' },
  { key: 'metering', label: 'Metering' },
]

interface DraftHardware {
  inverters: JobHardwareItem[]
  batteries: JobHardwareItem[]
  metering: JobHardwareItem[]
  panel: JobHardwarePanel
  panelModelOptions: string // textarea, one option per line
  siteNotes: JobHardwareSiteNotes
  warnings: string // textarea, one warning per line
}

function toDraft(hw: JobHardwareSnapshot | null | undefined): DraftHardware {
  return {
    inverters: (hw?.inverters ?? []).map((it) => ({ ...it })),
    batteries: (hw?.batteries ?? []).map((it) => ({ ...it })),
    metering: (hw?.metering ?? []).map((it) => ({ ...it })),
    panel: { ...(hw?.panel ?? {}) },
    panelModelOptions: (hw?.panel?.model_options ?? []).join('\n'),
    siteNotes: { ...(hw?.site_notes ?? {}) },
    warnings: (hw?.warnings ?? []).join('\n'),
  }
}

function parseLines(s: string): string[] {
  return s
    .split('\n')
    .map((x) => x.trim())
    .filter(Boolean)
}

function panelHasContent(p: JobHardwarePanel): boolean {
  return Object.values(p).some((v) => v != null && !(Array.isArray(v) && v.length === 0) && v !== '')
}

// Build the whole hardware object to PATCH. Sends every sub-section so the saved snapshot matches
// the editor exactly (empty list / null panel clear it); provenance fields are carried untouched.
function fromDraft(d: DraftHardware): JobHardwareSnapshot {
  const options = parseLines(d.panelModelOptions)
  const panel: JobHardwarePanel = { ...d.panel, model_options: options.length ? options : null }
  return {
    inverters: d.inverters,
    batteries: d.batteries,
    metering: d.metering,
    panel: panelHasContent(panel) ? panel : null,
    site_notes: d.siteNotes,
    warnings: parseLines(d.warnings),
  }
}

function numOrNull(v: string): number | null {
  if (v.trim() === '') return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

export function JobHardwareSection({ job }: { job: Job }) {
  const { user } = useAuth()
  const canEdit = canEditJobDetails(user?.role.name)
  const updateMutation = useUpdateJob(job.id)

  const hardware = job.details?.hardware ?? null
  const detailsIsNull = job.details == null

  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<DraftHardware>(() => toDraft(hardware))
  const [error, setError] = useState<string | null>(null)

  function startEdit() {
    setError(null)
    setDraft(toDraft(hardware))
    setEditing(true)
  }
  function cancel() {
    setError(null)
    setEditing(false)
  }
  async function save() {
    setError(null)
    try {
      await updateMutation.mutateAsync({ details: { hardware: fromDraft(draft) } })
      setEditing(false)
    } catch (err) {
      setError(describeError(err))
    }
  }

  // ---- draft mutation helpers ----
  function setItem(kind: ItemKind, idx: number, patch: Partial<JobHardwareItem>) {
    setDraft((d) => {
      const list = d[kind].map((it, i) => (i === idx ? { ...it, ...patch } : it))
      return { ...d, [kind]: list }
    })
  }
  function addItem(kind: ItemKind) {
    setDraft((d) => ({ ...d, [kind]: [...d[kind], { model_text: '', quantity: null }] }))
  }
  function removeItem(kind: ItemKind, idx: number) {
    setDraft((d) => ({ ...d, [kind]: d[kind].filter((_, i) => i !== idx) }))
  }
  function setPanel(patch: Partial<JobHardwarePanel>) {
    setDraft((d) => ({ ...d, panel: { ...d.panel, ...patch } }))
  }
  function setSiteNote(patch: Partial<JobHardwareSiteNotes>) {
    setDraft((d) => ({ ...d, siteNotes: { ...d.siteNotes, ...patch } }))
  }

  return (
    <div className="card p-5">
      <div className="mb-1 flex items-center justify-between gap-3">
        <h2 className="eyebrow">Hardware</h2>
        {canEdit && !detailsIsNull && !editing && (
          <button onClick={startEdit} className="btn-secondary px-3 py-1 text-sm">
            Edit
          </button>
        )}
      </div>
      <p className="mb-3 text-xs text-faint">{SNAPSHOT_NOTE}</p>

      {error && (
        <div className="mb-3 rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
          {error}
        </div>
      )}

      {detailsIsNull ? (
        <p className="text-sm text-muted">
          Hardware editing is available once structured job details exist.
        </p>
      ) : editing ? (
        <HardwareEditor
          draft={draft}
          pending={updateMutation.isPending}
          onItem={setItem}
          onAddItem={addItem}
          onRemoveItem={removeItem}
          onPanel={setPanel}
          onPanelModelOptions={(v) => setDraft((d) => ({ ...d, panelModelOptions: v }))}
          onSiteNote={setSiteNote}
          onWarnings={(v) => setDraft((d) => ({ ...d, warnings: v }))}
          onSave={save}
          onCancel={cancel}
        />
      ) : (
        <HardwareView hardware={hardware} />
      )}
    </div>
  )
}

// --------------------------------------------------------------------------- //
// Read-only view
// --------------------------------------------------------------------------- //
function HardwareView({ hardware }: { hardware: JobHardwareSnapshot | null }) {
  const lists = ITEM_KINDS.map((k) => ({ ...k, items: hardware?.[k.key] ?? [] }))
  const panel = hardware?.panel ?? null
  const warnings = hardware?.warnings ?? []
  const site = hardware?.site_notes ?? null
  const isEmpty =
    lists.every((l) => l.items.length === 0) &&
    !panel &&
    warnings.length === 0 &&
    !(site && Object.values(site).some((v) => v != null && v !== ''))

  if (isEmpty) return <p className="text-sm text-muted">No hardware recorded.</p>

  return (
    <div className="flex flex-col gap-4 text-sm">
      {lists.map((l) =>
        l.items.length === 0 ? null : (
          <div key={l.key}>
            <p className="eyebrow text-faint">{l.label}</p>
            <ul className="mt-1 flex flex-col gap-1">
              {l.items.map((it, i) => (
                <li key={i} className="text-fg">
                  {(it.model_text ?? '—') || '—'}
                  {it.quantity != null && <span className="text-muted"> × {it.quantity}</span>}
                  <ItemProvenance item={it} />
                </li>
              ))}
            </ul>
          </div>
        ),
      )}

      {panel && (
        <div>
          <p className="eyebrow text-faint">Panel</p>
          <p className="mt-1 text-fg">
            {panel.display_name || panel.model || '—'}
            {panel.quantity != null && <span className="text-muted"> × {panel.quantity}</span>}
          </p>
          <p className="text-xs text-muted">
            {[
              panel.brand,
              panel.wattage_w != null ? `${panel.wattage_w} W` : null,
              panel.panel_array_kw != null ? `${panel.panel_array_kw} kW` : null,
              panel.model && panel.model !== panel.display_name ? panel.model : null,
            ]
              .filter(Boolean)
              .join(' · ') || null}
          </p>
          {panel.model_options && panel.model_options.length > 0 && (
            <p className="text-xs text-faint">Options: {panel.model_options.join(', ')}</p>
          )}
        </div>
      )}

      {site && Object.values(site).some((v) => v != null && v !== '') && (
        <div>
          <p className="eyebrow text-faint">Site notes</p>
          <p className="mt-1 text-xs text-muted">
            {[
              site.ct ? `CT: ${site.ct}` : null,
              site.export_limit ? `Export: ${site.export_limit}` : null,
              site.underground ? `Underground: ${site.underground}` : null,
              site.comms ? `Comms: ${site.comms}` : null,
            ]
              .filter(Boolean)
              .join(' · ') || '—'}
          </p>
        </div>
      )}

      {warnings.length > 0 && (
        <div>
          <p className="eyebrow text-faint">Warnings</p>
          <ul className="mt-1 flex flex-wrap gap-2">
            {warnings.map((w, i) => (
              <li
                key={i}
                className="rounded bg-amber-500/10 px-2 py-0.5 text-xs text-amber-300"
              >
                {w}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

// Subtle, non-noisy provenance (confidence / source / parser-owned) — only when present.
function ItemProvenance({ item }: { item: JobHardwareItem }) {
  const bits = [
    item.confidence ?? null,
    item.parser_owned ? 'parser' : item.source_type ?? null,
    item.source_fragment ? `“${item.source_fragment}”` : null,
  ].filter(Boolean)
  if (bits.length === 0) return null
  return <span className="ml-2 text-xs text-faint">· {bits.join(' · ')}</span>
}

// --------------------------------------------------------------------------- //
// Editor
// --------------------------------------------------------------------------- //
interface EditorProps {
  draft: DraftHardware
  pending: boolean
  onItem: (kind: ItemKind, idx: number, patch: Partial<JobHardwareItem>) => void
  onAddItem: (kind: ItemKind) => void
  onRemoveItem: (kind: ItemKind, idx: number) => void
  onPanel: (patch: Partial<JobHardwarePanel>) => void
  onPanelModelOptions: (v: string) => void
  onSiteNote: (patch: Partial<JobHardwareSiteNotes>) => void
  onWarnings: (v: string) => void
  onSave: () => void
  onCancel: () => void
}

function HardwareEditor(p: EditorProps) {
  const { draft } = p
  return (
    <div className="flex flex-col gap-5 text-sm">
      {ITEM_KINDS.map(({ key, label }) => (
        <div key={key}>
          <div className="mb-1 flex items-center justify-between">
            <p className="eyebrow text-faint">{label}</p>
            <button
              type="button"
              onClick={() => p.onAddItem(key)}
              className="text-xs font-medium text-brand-400 hover:text-brand-300"
            >
              + Add
            </button>
          </div>
          {draft[key].length === 0 ? (
            <p className="text-xs text-muted">None.</p>
          ) : (
            <div className="flex flex-col gap-2">
              {draft[key].map((it, i) => (
                <div key={i} className="flex items-center gap-2">
                  <input
                    value={it.model_text ?? ''}
                    onChange={(e) => p.onItem(key, i, { model_text: e.target.value })}
                    placeholder="Model text"
                    className="input flex-1 px-2 py-1"
                  />
                  <input
                    type="number"
                    value={it.quantity ?? ''}
                    onChange={(e) => p.onItem(key, i, { quantity: numOrNull(e.target.value) })}
                    placeholder="Qty"
                    className="input w-20 px-2 py-1"
                  />
                  <button
                    type="button"
                    onClick={() => p.onRemoveItem(key, i)}
                    className="text-xs font-medium text-red-300 hover:text-red-200"
                  >
                    Remove
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      ))}

      <div>
        <p className="eyebrow mb-1 text-faint">Panel</p>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          <Labelled label="Display name">
            <input
              value={draft.panel.display_name ?? ''}
              onChange={(e) => p.onPanel({ display_name: e.target.value })}
              className="input px-2 py-1"
            />
          </Labelled>
          <Labelled label="Model">
            <input
              value={draft.panel.model ?? ''}
              onChange={(e) => p.onPanel({ model: e.target.value })}
              className="input px-2 py-1"
            />
          </Labelled>
          <Labelled label="Brand">
            <input
              value={draft.panel.brand ?? ''}
              onChange={(e) => p.onPanel({ brand: e.target.value })}
              className="input px-2 py-1"
            />
          </Labelled>
          <Labelled label="Quantity">
            <input
              type="number"
              value={draft.panel.quantity ?? ''}
              onChange={(e) => p.onPanel({ quantity: numOrNull(e.target.value) })}
              className="input px-2 py-1"
            />
          </Labelled>
          <Labelled label="Wattage (W)">
            <input
              type="number"
              value={draft.panel.wattage_w ?? ''}
              onChange={(e) => p.onPanel({ wattage_w: numOrNull(e.target.value) })}
              className="input px-2 py-1"
            />
          </Labelled>
          <Labelled label="Array size (kW)">
            <input
              type="number"
              value={draft.panel.panel_array_kw ?? ''}
              onChange={(e) => p.onPanel({ panel_array_kw: numOrNull(e.target.value) })}
              className="input px-2 py-1"
            />
          </Labelled>
          <Labelled label="Model options (one per line)" full>
            <textarea
              rows={2}
              value={draft.panelModelOptions}
              onChange={(e) => p.onPanelModelOptions(e.target.value)}
              className="input px-2 py-1"
            />
          </Labelled>
        </div>
      </div>

      <div>
        <p className="eyebrow mb-1 text-faint">Site notes</p>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          <Labelled label="CT">
            <input
              value={draft.siteNotes.ct ?? ''}
              onChange={(e) => p.onSiteNote({ ct: e.target.value })}
              className="input px-2 py-1"
            />
          </Labelled>
          <Labelled label="Export limit">
            <input
              value={draft.siteNotes.export_limit ?? ''}
              onChange={(e) => p.onSiteNote({ export_limit: e.target.value })}
              className="input px-2 py-1"
            />
          </Labelled>
          <Labelled label="Underground">
            <input
              value={draft.siteNotes.underground ?? ''}
              onChange={(e) => p.onSiteNote({ underground: e.target.value })}
              className="input px-2 py-1"
            />
          </Labelled>
          <Labelled label="Comms">
            <input
              value={draft.siteNotes.comms ?? ''}
              onChange={(e) => p.onSiteNote({ comms: e.target.value })}
              className="input px-2 py-1"
            />
          </Labelled>
        </div>
      </div>

      <Labelled label="Warnings (one per line)" full>
        <textarea
          rows={2}
          value={draft.warnings}
          onChange={(e) => p.onWarnings(e.target.value)}
          className="input px-2 py-1"
        />
      </Labelled>

      <div className="flex justify-end gap-3">
        <button type="button" onClick={p.onCancel} className="btn-secondary text-sm">
          Cancel
        </button>
        <button
          type="button"
          onClick={p.onSave}
          disabled={p.pending}
          className="btn-primary text-sm disabled:opacity-50"
        >
          {p.pending ? 'Saving…' : 'Save hardware'}
        </button>
      </div>
    </div>
  )
}

function Labelled({
  label,
  full,
  children,
}: {
  label: string
  full?: boolean
  children: ReactNode
}) {
  return (
    <label className={`block ${full ? 'sm:col-span-2' : ''}`}>
      <span className="eyebrow mb-1 block text-faint">{label}</span>
      {children}
    </label>
  )
}

function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 422) {
      return 'Could not save hardware — a value is invalid (check quantities/sizes).'
    }
    if (err.status === 403) return 'You do not have permission to edit job hardware.'
    if (err.status === 404) return 'This job no longer exists. Refresh and try again.'
  }
  return 'Could not save hardware. Please try again.'
}
