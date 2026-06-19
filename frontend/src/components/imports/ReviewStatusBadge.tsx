// Small badges for import row class + review status.

import type { ImportRowClass, ImportRowReviewStatus } from '@/types/imports'

const REVIEW_STATUS_STYLES: Record<ImportRowReviewStatus, string> = {
  pending: 'bg-elevated text-muted',
  approved: 'bg-emerald-500/15 text-emerald-300',
  rejected: 'bg-red-500/15 text-red-300',
  skipped: 'bg-amber-500/15 text-amber-300',
  committed: 'bg-brand-500/15 text-brand-300',
  reversed: 'bg-zinc-500/20 text-zinc-300',
}

// eslint-disable-next-line react-refresh/only-export-components -- display lookup co-located with its badge
export const REVIEW_STATUS_LABELS: Record<ImportRowReviewStatus, string> = {
  pending: 'Pending',
  approved: 'Approved',
  rejected: 'Rejected',
  skipped: 'Skipped',
  committed: 'Committed',
  reversed: 'Reversed',
}

// eslint-disable-next-line react-refresh/only-export-components -- display lookup co-located with its badge
export const REVIEW_STATUS_ORDER: ImportRowReviewStatus[] = [
  'pending',
  'approved',
  'rejected',
  'skipped',
  'committed',
  'reversed',
]

export function ReviewStatusBadge({ status }: { status: ImportRowReviewStatus }) {
  return (
    <span
      className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${REVIEW_STATUS_STYLES[status]}`}
    >
      {REVIEW_STATUS_LABELS[status]}
    </span>
  )
}

const ROW_CLASS_STYLES: Record<ImportRowClass, string> = {
  job: 'bg-brand-500/15 text-brand-300',
  ambiguous: 'bg-amber-500/15 text-amber-300',
  divider: 'bg-elevated text-faint',
  blank: 'bg-elevated text-faint',
}

// eslint-disable-next-line react-refresh/only-export-components -- display lookup co-located with its badge
export const ROW_CLASS_LABELS: Record<ImportRowClass, string> = {
  job: 'Job',
  ambiguous: 'Ambiguous',
  divider: 'Divider',
  blank: 'Blank',
}

// eslint-disable-next-line react-refresh/only-export-components -- display lookup co-located with its badge
export const ROW_CLASS_ORDER: ImportRowClass[] = ['job', 'ambiguous', 'divider', 'blank']

export function RowClassBadge({ rowClass }: { rowClass: ImportRowClass }) {
  return (
    <span
      className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${ROW_CLASS_STYLES[rowClass]}`}
    >
      {ROW_CLASS_LABELS[rowClass]}
    </span>
  )
}
