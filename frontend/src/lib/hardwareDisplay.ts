// Job-facing display + edit mapping for a Job.details.hardware snapshot (Hardware Parser lane).
//
// The parsed hardware appears as NORMAL Job Detail System fields (Panel type / Inverter / Battery /
// Metering·CT) — the current parsed/editable VALUE always shows, regardless of confidence. Low
// confidence does NOT hide the value; it only adds a supplemental "Hardware notes" flag. An item's
// quantity is shown inline as "N × MODEL" when > 1 (and round-trips on edit), so an explicit
// hardware quantity is never lost. CT / export / underground / comms site-notes show read-only.
// Pure + read-only derivation (no catalogue lookup); editing maps a textbox back into
// details.hardware (see applyHardwareSystemEdits).

import type { JobHardwareItem, JobHardwarePanel, JobHardwareSnapshot } from '@/types/imports'

const LOW_CONFIDENCE = new Set(['unconfirmed_raw_text', 'manual_review'])

function itemModelText(it: JobHardwareItem): string {
  return (it.model_text ?? '').trim()
}

function panelDisplay(p: JobHardwarePanel | null | undefined): string {
  if (!p) return ''
  if (p.display_name?.trim()) return p.display_name.trim()
  if (p.model?.trim()) return p.model.trim()
  return [p.brand?.trim(), p.wattage_w != null ? `${p.wattage_w}W` : null].filter(Boolean).join(' ')
}

/** "N × MODEL" when a quantity > 1 is recorded, else just the model text (empty when blank). */
function formatItem(it: JobHardwareItem): string {
  const text = itemModelText(it)
  if (!text) return ''
  return it.quantity != null && it.quantity > 1 ? `${it.quantity} × ${text}` : text
}

function joinModels(items: JobHardwareItem[] | null | undefined): string {
  return (items ?? []).map(formatItem).filter(Boolean).join(', ')
}

// Parse a System-hardware textbox entry back into quantity + model text — the inverse of
// `formatItem`, so a displayed "2 × MODEL" round-trips to quantity 2 + model_text "MODEL" rather
// than baking the quantity into the model text. Accepts x / × / * separators.
const _QTY_PREFIX_RE = /^\s*(\d+)\s*[x×*]\s*(.*\S)\s*$/i

function splitQtyModel(entry: string): { quantity: number | null; modelText: string } {
  const m = entry.match(_QTY_PREFIX_RE)
  if (m && m[1] && m[2]) return { quantity: parseInt(m[1], 10), modelText: m[2].trim() }
  return { quantity: null, modelText: entry.trim() }
}

function siteNoteBits(hw: JobHardwareSnapshot): string[] {
  const s = hw.site_notes
  if (!s) return []
  return [
    s.ct?.length ? `CT: ${s.ct.join(', ')}` : null,
    s.export_limit?.length ? `Export: ${s.export_limit.join(', ')}` : null,
    s.underground?.length ? `Underground: ${s.underground.join(', ')}` : null,
    s.comms?.length ? `Comms: ${s.comms.join(', ')}` : null,
  ].filter((x): x is string => !!x)
}

export interface SystemHardwareField {
  key: string
  label: string
  value: string
  editable: boolean
}

/**
 * The hardware values shown as normal System fields. Panel type / Inverter / Battery are always
 * present + editable when a snapshot exists (so the value is visible and correctable regardless of
 * confidence); Metering·CT shows when there's metering/CT evidence; the CT/electrical site notes
 * show read-only. Number-of-panels / Storey / Phase / Roof type remain the existing registry fields.
 */
export function deriveSystemHardware(
  hw: JobHardwareSnapshot | null | undefined,
): SystemHardwareField[] {
  if (!hw) return []
  const out: SystemHardwareField[] = [
    { key: 'hw_panel', label: 'Panel type', value: panelDisplay(hw.panel), editable: true },
    { key: 'hw_inverter', label: 'Inverter', value: joinModels(hw.inverters), editable: true },
    { key: 'hw_battery', label: 'Battery', value: joinModels(hw.batteries), editable: true },
  ]
  const meteringValue = joinModels(hw.metering)
  if (meteringValue || (hw.metering?.length ?? 0) > 0) {
    out.push({ key: 'hw_metering', label: 'Metering', value: meteringValue, editable: true })
  }
  const site = siteNoteBits(hw)
  if (site.length) {
    // Parsed electrical evidence (CT / export / underground / comms) — read-only in this pass.
    out.push({ key: 'hw_site', label: 'CT / electrical', value: site.join(' · '), editable: false })
  }
  return out
}

/** Supplemental "Hardware notes" only: confidence flags, ambiguous options, warnings, misc — NEVER
 *  the only place the inverter/battery values appear (those are System fields above). */
export function deriveHardwareNotes(hw: JobHardwareSnapshot | null | undefined): string[] {
  if (!hw) return []
  const notes: string[] = []
  const flag = (label: string, it: JobHardwareItem) => {
    if (it.confidence && LOW_CONFIDENCE.has(it.confidence) && itemModelText(it)) {
      notes.push(`${label} “${itemModelText(it)}” — ${it.confidence} (review)`)
    }
  }
  for (const i of hw.inverters ?? []) flag('Inverter', i)
  for (const b of hw.batteries ?? []) flag('Battery', b)
  for (const m of hw.metering ?? []) flag('Metering', m)
  if (hw.panel?.confidence && LOW_CONFIDENCE.has(hw.panel.confidence)) {
    notes.push(`Panel “${panelDisplay(hw.panel)}” — ${hw.panel.confidence} (review)`)
  }
  if (hw.panel?.model_options?.length) notes.push(`Panel options: ${hw.panel.model_options.join(', ')}`)
  for (const m of hw.site_notes?.raw_misc ?? []) notes.push(`Note: ${m}`)
  for (const w of hw.warnings ?? []) notes.push(w)
  return notes
}

// --- Editing: map an edited System-hardware textbox back into details.hardware --------------- //

function textToItems(value: string, original: JobHardwareItem[] | null | undefined): JobHardwareItem[] {
  const entries = value.split(',').map((s) => s.trim()).filter(Boolean)
  // Common case (a single item retext): preserve its provenance, just update text + quantity. A
  // "2 × MODEL" entry splits back into quantity 2 + model "MODEL" (the inverse of the display).
  if (entries.length === 1 && original && original.length === 1) {
    // The textbox always shows the "N ×" prefix when quantity > 1, so its absence means quantity 1.
    const { quantity, modelText } = splitQtyModel(entries[0] ?? '')
    return [{ ...original[0], model_text: modelText, quantity: quantity ?? 1 }]
  }
  // Otherwise it is a manual edit — rebuild as manual items (quantity from the "N ×" prefix, else 1).
  return entries.map((entry) => {
    const { quantity, modelText } = splitQtyModel(entry)
    return { model_text: modelText, quantity: quantity ?? 1, parser_owned: false, source_type: 'manual' }
  })
}

/** Build the PARTIAL details.hardware patch from edited System-hardware fields. Only edited
 *  sub-sections are returned (the backend replaces those and preserves the rest); returns null when
 *  there are no edits. Never touches Settings > Hardware / the catalogue — only the Job snapshot. */
export function applyHardwareSystemEdits(
  hw: JobHardwareSnapshot | null | undefined,
  edits: Record<string, string>,
): Partial<JobHardwareSnapshot> | null {
  const keys = Object.keys(edits)
  if (keys.length === 0) return null
  const patch: Partial<JobHardwareSnapshot> = {}
  if ('hw_panel' in edits) {
    const name = edits.hw_panel.trim()
    patch.panel = { ...(hw?.panel ?? {}), display_name: name || null, parser_owned: false }
  }
  if ('hw_inverter' in edits) patch.inverters = textToItems(edits.hw_inverter, hw?.inverters)
  if ('hw_battery' in edits) patch.batteries = textToItems(edits.hw_battery, hw?.batteries)
  if ('hw_metering' in edits) patch.metering = textToItems(edits.hw_metering, hw?.metering)
  return patch
}
