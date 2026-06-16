// Read-only preview of what import commit will seed into Job.internal_notes.
//
// MIRRORS the backend app/services/import_details.py `build_imported_notes` (P2):
//   * heading "Uncategorised Data on Import"
//   * bare bullets — the source-column label is NOT shown
//   * bare approval/status markers are excluded (state is structured separately),
//     but an approval REFERENCE NUMBER is kept (owner R2: useful context)
//   * bare no-value / no-panel placeholders are excluded
//   * identical lines are de-duplicated
//
// This is a PREVIEW ONLY — the authoritative value is still derived on the backend
// at commit time (seed_internal_notes -> build_imported_notes). Pre-commit editing
// of internal_notes is not yet supported (see the P5 report). A future backend
// follow-up that returns the authoritative preview / accepts an override would
// remove this client-side duplication.

import type { ParsedDetails } from '@/types/imports'

const APPROVAL_CONTEXT = /\bapprov(?:al|als|ed|e|ing)?\b/i
// A genuine approval REFERENCE NUMBER (#/No/Ref/Number + digits, or a 6+ digit
// run) is useful context KEPT in internal notes — unlike a bare status marker.
// Mirrors backend _APPROVAL_REF_NUMBER_RE (owner R2).
const APPROVAL_REF_NUMBER = /(?:#|\bno\b\.?|\bref(?:erence)?\b\.?|\bnumber\b)\s*\.?\s*\d{3,}|\b\d{6,}\b/i
const PANEL_PLACEHOLDERS = new Set(['n/a', 'na', 'nil', 'none', 'no panels', 'no panel'])

function isApprovalContextNote(text: string): boolean {
  if (!APPROVAL_CONTEXT.test(text)) return false
  if (APPROVAL_REF_NUMBER.test(text)) return false // keep: a real reference number
  return true
}

function isEmptyPanelPlaceholder(text: string): boolean {
  // Strip surrounding whitespace / dashes / dots; a residue-free string is junk.
  const stripped = text.toLowerCase().replace(/^[\s\-–—.]+|[\s\-–—.]+$/g, '')
  if (stripped === '') return true
  return PANEL_PLACEHOLDERS.has(stripped)
}

export const INTERNAL_NOTES_HEADING = 'Uncategorised Data on Import'

/**
 * The exact text import commit would seed into Job.internal_notes for this row,
 * or null when nothing useful would be preserved (internal_notes left blank).
 */
export function previewInternalNotes(details: ParsedDetails | null | undefined): string | null {
  const notes = details?.notes ?? {}
  const lines: string[] = []
  const seen = new Set<string>()

  const add = (raw: string | null | undefined): void => {
    const t = (raw ?? '').trim()
    if (!t) return
    if (isApprovalContextNote(t) || isEmptyPanelPlaceholder(t)) return
    const line = `- ${t}`
    if (!seen.has(line)) {
      seen.add(line)
      lines.push(line)
    }
  }

  add(notes.customer_name_notes ?? null)
  for (const m of notes.review_notes ?? []) add(m.text ?? null)
  for (const m of notes.misfiled ?? []) add(m.text ?? null)

  if (lines.length === 0) return null
  return `${INTERNAL_NOTES_HEADING}\n${lines.join('\n')}`
}
