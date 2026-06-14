// Display-only helper: parse an imported job's dense detail strings into
// structured sections for the Job detail page. Pure string parsing — it never
// drops information (unparseable input is kept as a bare value) and it does not
// touch the backend or the import mapping.
//
// Imported detail strings (built by the import commit) look like:
//   system_details / install_details / approval_details:  "Label: value | Label: value"
//   notes (newline-joined):  "Salesperson: …", "Payment — k: v, k: v",
//                            "Compliance — k: v", "Notes: …",
//                            "Imported from legacy workbook (batch N, row M…)."

import type { Job } from '@/types'

export interface DetailRow {
  label: string | null
  value: string
}

export interface ImportedJobView {
  system: DetailRow[]
  install: DetailRow[]
  approval: DetailRow[]
  payment: DetailRow[]
  compliance: DetailRow[]
  provenance: string[]
  otherNotes: DetailRow[]
}

function splitFields(text: string, separator: string): DetailRow[] {
  return text
    .split(separator)
    .map((s) => s.trim())
    .filter(Boolean)
    .map((seg) => {
      const i = seg.indexOf(':')
      if (i === -1) return { label: null, value: seg } // keep raw value, no label
      return { label: seg.slice(0, i).trim(), value: seg.slice(i + 1).trim() }
    })
}

/** A job is "imported" if the commit stamped the provenance line into its notes. */
export function isImportedJob(job: Pick<Job, 'notes'>): boolean {
  return /Imported from legacy workbook/.test(job.notes ?? '')
}

/**
 * Parse an imported job's detail/notes blobs into structured sections.
 * Returns null for non-imported jobs (caller falls back to plain rendering).
 */
export function parseImportedJobDetails(
  job: Pick<Job, 'system_details' | 'install_details' | 'approval_details' | 'notes'>,
): ImportedJobView | null {
  if (!isImportedJob(job)) return null

  const view: ImportedJobView = {
    system: splitFields(job.system_details ?? '', '|'),
    install: splitFields(job.install_details ?? '', '|'),
    approval: splitFields(job.approval_details ?? '', '|'),
    payment: [],
    compliance: [],
    provenance: [],
    otherNotes: [],
  }

  const lines = (job.notes ?? '')
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean)

  for (const line of lines) {
    if (/^Imported from legacy workbook/i.test(line)) {
      view.provenance.push(line)
    } else if (/^Payment\s*[—–-]\s*/.test(line)) {
      view.payment.push(...splitFields(line.replace(/^Payment\s*[—–-]\s*/, ''), ','))
    } else if (/^Compliance\s*[—–-]\s*/.test(line)) {
      view.compliance.push(...splitFields(line.replace(/^Compliance\s*[—–-]\s*/, ''), ','))
    } else {
      // "Salesperson: …", "Notes: …", "Other emails/phones: …", or free text.
      const i = line.indexOf(':')
      if (i === -1) view.otherNotes.push({ label: null, value: line })
      else view.otherNotes.push({ label: line.slice(0, i).trim(), value: line.slice(i + 1).trim() })
    }
  }

  return view
}
