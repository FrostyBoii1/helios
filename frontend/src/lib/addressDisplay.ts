// Shared read-only formatting for a parsed/job site address (G `details.site`).
// Used by the import review modal (Item 4 pre-commit "Property address") and the
// candidate row preview, so both render the cleaned structured address identically.

import type { ParsedCandidate, SiteAddress } from '@/types/imports'

/** "line1, line2, Suburb STATE postcode" from a site address, or '' if none/empty. */
export function siteLine(s: SiteAddress | null | undefined): string {
  if (!s) return ''
  const city = [s.suburb, s.state, s.postcode]
    .map((p) => (p ? String(p).trim() : ''))
    .filter(Boolean)
    .join(' ')
  return [s.line1, s.line2, city]
    .map((p) => (p ? String(p).trim() : ''))
    .filter(Boolean)
    .join(', ')
}

/** The cleaned editable Address value for a parsed row: `siteLine(details.site)` when the
 *  parser produced a structured site address, else `null` (callers fall back to the raw
 *  `parsed.address`). Item 4: the import review modal seeds the editable Address field with
 *  this and baselines edit-detection against it, so the raw parsed.address is never silently
 *  overwritten by a no-op save. */
export function cleanedAddressValue(parsed: ParsedCandidate | null | undefined): string | null {
  const site = parsed?.details?.site
  if (!site) return null
  return siteLine(site) || null
}
