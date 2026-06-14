// Shared helpers for building a path-restricted structured `details` patch from
// string UI edits keyed by "<section>.<key>" (the StructuredDetailsView edit
// shape). Used by both the import review drawer (row.parsed.details) and the
// live Job detail page (job.details) — the coercion + change detection must match
// so the two surfaces send identical patches to the same backend whitelist.

import type { FieldSpec, ParsedDetails } from '@/types/imports'

// Coerce a string UI value to its stored type at save time:
// number -> integer or null, empty -> null, else trimmed string.
export function coerceDetail(raw: string, inputType: string | undefined): unknown {
  const trimmed = raw.trim()
  if (trimmed === '') return null
  if (inputType === 'number') {
    const n = parseInt(trimmed, 10)
    return Number.isFinite(n) ? n : null
  }
  return trimmed
}

// Read a nested "<section>.<key>" value out of a registry-shaped details object.
export function detailValueAt(details: ParsedDetails | null | undefined, path: string): unknown {
  if (!details) return undefined
  let cur: unknown = details
  for (const p of path.split('.')) {
    if (cur == null || typeof cur !== 'object') return undefined
    cur = (cur as Record<string, unknown>)[p]
  }
  return cur
}

// Compare a coerced value against the current stored value (null-aware, stringy).
export function sameDetail(a: unknown, b: unknown): boolean {
  if (a == null && b == null) return true
  if (a == null || b == null) return false
  return String(a) === String(b)
}

// Build a nested `{section: {key: value}}` patch from touched-and-changed leaves,
// coerced by each field's input_type. Returns null when nothing changed.
export function buildDetailsPatch(
  edits: Record<string, string>,
  details: ParsedDetails | null | undefined,
  fieldByPath: Map<string, FieldSpec>,
): Record<string, Record<string, unknown>> | null {
  const patch: Record<string, Record<string, unknown>> = {}
  for (const [path, raw] of Object.entries(edits)) {
    const coerced = coerceDetail(raw, fieldByPath.get(path)?.input_type)
    if (sameDetail(coerced, detailValueAt(details, path))) continue
    const dot = path.indexOf('.')
    if (dot < 0) continue
    const section = path.slice(0, dot)
    const key = path.slice(dot + 1)
    ;(patch[section] ??= {})[key] = coerced
  }
  return Object.keys(patch).length > 0 ? patch : null
}
