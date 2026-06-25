// Job-facing display + edit mapping for a Job.details.hardware snapshot (Hardware Parser lane).
//
// The parsed hardware appears as NORMAL Job Detail System fields (Panel type / Inverter / Battery /
// Metering·CT) — the current parsed/editable VALUE always shows, regardless of confidence. Low
// confidence does NOT hide the value; it only adds a supplemental "Hardware notes" flag. An item's
// quantity is shown inline as "N × MODEL" when > 1 (and round-trips on edit), so an explicit
// hardware quantity is never lost. CT / export / underground / comms site-notes show read-only.
// Pure + read-only derivation (no catalogue lookup); editing maps a textbox back into
// details.hardware (see applyHardwareSystemEdits).

import type { HardwareCategory } from '@/types'
import type { JobHardwareItem, JobHardwarePanel, JobHardwareSnapshot, ParsedDetails } from '@/types/imports'

const LOW_CONFIDENCE = new Set(['unconfirmed_raw_text', 'manual_review'])

function anyLowConfidence(items: JobHardwareItem[] | null | undefined): boolean {
  return (items ?? []).some((it) => it.confidence != null && LOW_CONFIDENCE.has(it.confidence))
}

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
  // The catalogue category this field searches (drives autocomplete); absent for read-only rows.
  category?: HardwareCategory
  // True when any item in this bucket is low-confidence/unconfirmed — surfaces an unobtrusive
  // "review" marker WITHOUT hiding the value or disabling the textbox.
  lowConfidence?: boolean
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
  const panelLow = hw.panel?.confidence != null && LOW_CONFIDENCE.has(hw.panel.confidence)
  const out: SystemHardwareField[] = [
    { key: 'hw_panel', label: 'Panel type', value: panelDisplay(hw.panel), editable: true,
      category: 'panel', lowConfidence: panelLow },
    { key: 'hw_inverter', label: 'Inverter', value: joinModels(hw.inverters), editable: true,
      category: 'inverter', lowConfidence: anyLowConfidence(hw.inverters) },
    { key: 'hw_battery', label: 'Battery', value: joinModels(hw.batteries), editable: true,
      category: 'battery', lowConfidence: anyLowConfidence(hw.batteries) },
  ]
  const meteringValue = joinModels(hw.metering)
  if (meteringValue || (hw.metering?.length ?? 0) > 0) {
    out.push({ key: 'hw_metering', label: 'Metering', value: meteringValue, editable: true,
               category: 'metering', lowConfidence: anyLowConfidence(hw.metering) })
  }
  const site = siteNoteBits(hw)
  if (site.length) {
    // Parsed electrical evidence (CT / export / underground / comms) — read-only in this pass.
    out.push({ key: 'hw_site', label: 'CT / electrical', value: site.join(' · '), editable: false })
  }
  return out
}

export interface HardwareContext {
  /** Humanised electrical phase (from details.system.phase); '' when unknown. */
  phase: string
  /** Panel display (display_name | model | brand + wattage); '' when none. */
  panels: string
  /** Inverter model(s) in the "N × MODEL" convention; '' when none. */
  inverter: string
  /** Battery model(s) in the "N × MODEL" convention; null when there is NO battery. */
  battery: string | null
}

const PHASE_LABELS: Record<string, string> = {
  single: 'Single-phase',
  two: 'Two-phase',
  three: 'Three-phase',
}

/**
 * The tight hardware-context block shown in the grouping-candidate preview: phase + panels +
 * inverter + battery ONLY (deliberately NOT metering / CT / site notes / roof / storey — that would
 * re-introduce a broad details dump). Phase comes from details.system.phase (NOT the hardware
 * snapshot); panels/inverter/battery reuse the same panelDisplay / "N × MODEL" conventions as the
 * System fields. Pure + read-only; `battery` is null when absent so the caller can hide that line.
 */
export function deriveHardwareContext(details: ParsedDetails | null | undefined): HardwareContext {
  const hw = details?.hardware ?? null
  const rawPhase = (details?.system as { phase?: unknown } | undefined)?.phase
  const phase =
    typeof rawPhase === 'string' && rawPhase.trim()
      ? (PHASE_LABELS[rawPhase.trim().toLowerCase()] ?? rawPhase.trim())
      : ''
  return {
    phase,
    panels: panelDisplay(hw?.panel),
    inverter: joinModels(hw?.inverters),
    battery: joinModels(hw?.batteries) || null,
  }
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

/** Provenance recorded when a user picks a catalogue result for a hardware field. Stamped onto the
 *  snapshot as `canonical_hardware_id_at_parse_time` (provenance/debug ONLY — never a live
 *  reference) + `confidence` (default `manual_correction`). `model` carries the catalogue
 *  canonical_model, used to set the panel `model` on a panel selection. */
export interface HardwareSelection {
  id: number
  confidence?: string
  model?: string | null
}

function textToItems(
  value: string,
  original: JobHardwareItem[] | null | undefined,
  selection?: HardwareSelection,
): JobHardwareItem[] {
  const entries = value.split(',').map((s) => s.trim()).filter(Boolean)
  // The one original source_fragment is kept as evidence (never invented); ALL other parser/
  // catalogue provenance is dropped on a manual edit (the visible text is the source of truth).
  const origFragment =
    original && original.length === 1 ? original[0]?.source_fragment ?? undefined : undefined

  // A single item (free-typed OR autocomplete-picked) becomes a fresh MANUAL item:
  // parser_owned=false, source_type=manual, confidence=manual_correction, and NO stale
  // canonical_hardware_id_at_parse_time / model / source_field / rule_version carried over. ONLY an
  // actual catalogue selection stamps the chosen canonical id. Quantity comes from any "N ×" prefix.
  if (entries.length === 1) {
    const { quantity, modelText } = splitQtyModel(entries[0] ?? '')
    const item: JobHardwareItem = {
      model_text: modelText,
      quantity: quantity ?? 1,
      confidence: selection?.confidence ?? 'manual_correction',
      parser_owned: false,
      source_type: 'manual',
    }
    if (selection) item.canonical_hardware_id_at_parse_time = selection.id
    if (origFragment) item.source_fragment = origFragment
    return [item]
  }
  // A comma list is a manual multi-item rebuild — fresh manual items, no carried provenance.
  return entries.map((entry) => {
    const { quantity, modelText } = splitQtyModel(entry)
    return {
      model_text: modelText,
      quantity: quantity ?? 1,
      confidence: 'manual_correction',
      parser_owned: false,
      source_type: 'manual',
    }
  })
}

/** Build the PARTIAL details.hardware patch from edited System-hardware fields. Only edited
 *  sub-sections are returned (the backend replaces those and preserves the rest); returns null when
 *  there are no edits. `selections` carries catalogue-pick provenance per field key. Never touches
 *  Settings > Hardware / the catalogue — only the Job (or import-row) snapshot. */
export function applyHardwareSystemEdits(
  hw: JobHardwareSnapshot | null | undefined,
  edits: Record<string, string>,
  selections?: Record<string, HardwareSelection>,
): Partial<JobHardwareSnapshot> | null {
  const keys = Object.keys(edits)
  if (keys.length === 0) return null
  const patch: Partial<JobHardwareSnapshot> = {}
  if ('hw_panel' in edits) {
    const name = edits.hw_panel.trim()
    const sel = selections?.hw_panel
    if (sel) {
      // Catalogue selection -> stamp the chosen id/model/confidence as provenance.
      patch.panel = {
        ...(hw?.panel ?? {}),
        display_name: name || null,
        parser_owned: false,
        canonical_hardware_id_at_parse_time: sel.id,
        confidence: sel.confidence ?? 'manual_correction',
        model: sel.model ?? null,
      }
    } else {
      // Free-typed -> the text is the source of truth. Keep ONLY the panel count (independent of the
      // model) + the single source_fragment as evidence; DROP all stale catalogue-model provenance
      // (canonical id / model / model_options / brand / wattage / array_kw / rule version) so the
      // panel can never display one model while silently carrying another's id.
      const panel: JobHardwarePanel = {
        display_name: name || null,
        parser_owned: false,
        confidence: 'manual_correction',
      }
      if (hw?.panel?.quantity != null) panel.quantity = hw.panel.quantity
      if (hw?.panel?.source_fragment) panel.source_fragment = hw.panel.source_fragment
      patch.panel = panel
    }
  }
  if ('hw_inverter' in edits) patch.inverters = textToItems(edits.hw_inverter, hw?.inverters, selections?.hw_inverter)
  if ('hw_battery' in edits) patch.batteries = textToItems(edits.hw_battery, hw?.batteries, selections?.hw_battery)
  if ('hw_metering' in edits) patch.metering = textToItems(edits.hw_metering, hw?.metering, selections?.hw_metering)
  return patch
}
