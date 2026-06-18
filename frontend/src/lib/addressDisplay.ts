// Shared read-only formatting for a parsed/job site address (G `details.site`).
// Used by the import review modal (Item 4 pre-commit "Property address") and the
// candidate row preview, so both render the cleaned structured address identically.

import type { Job } from '@/types'
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

/** Distinct job-site addresses for a customer, formatted via `siteLine()`, in first-seen
 *  order. Reads each job's `details.site`, skips jobs with no usable site (including
 *  pre-G `details === null`), and dedupes case-insensitively. Stage 1: drives the
 *  read-only Customer-Detail "Job sites" summary. Pure — no side effects. */
export function distinctJobSites(jobs: Job[]): string[] {
  const out: string[] = []
  const seen = new Set<string>()
  for (const job of jobs) {
    const line = siteLine(job.details?.site).trim()
    if (!line) continue
    const key = line.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    out.push(line)
  }
  return out
}
