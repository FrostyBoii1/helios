// Compact issue-severity badges (counts by severity for a row).

import type { ImportIssue, ImportIssueSeverity } from '@/types/imports'

const SEVERITY_STYLES: Record<ImportIssueSeverity, string> = {
  error: 'bg-red-500/15 text-red-300',
  warning: 'bg-amber-500/15 text-amber-300',
  info: 'bg-sky-500/15 text-sky-300',
}

export const SEVERITY_LABELS: Record<ImportIssueSeverity, string> = {
  error: 'Error',
  warning: 'Warning',
  info: 'Info',
}

export const SEVERITY_ORDER: ImportIssueSeverity[] = ['error', 'warning', 'info']

/** Inline counts of unresolved issues by severity. Resolved issues are excluded. */
export function IssueBadges({ issues }: { issues: ImportIssue[] }) {
  const counts: Record<ImportIssueSeverity, number> = { error: 0, warning: 0, info: 0 }
  for (const issue of issues) {
    if (!issue.resolved) counts[issue.severity] += 1
  }
  const visible = SEVERITY_ORDER.filter((s) => counts[s] > 0)
  if (visible.length === 0) {
    return <span className="text-xs text-faint">—</span>
  }
  return (
    <span className="flex flex-wrap gap-1">
      {visible.map((s) => (
        <span
          key={s}
          className={`inline-block rounded px-1.5 py-0.5 text-xs font-medium ${SEVERITY_STYLES[s]}`}
          title={`${counts[s]} unresolved ${SEVERITY_LABELS[s].toLowerCase()}${counts[s] > 1 ? 's' : ''}`}
        >
          {counts[s]} {SEVERITY_LABELS[s].toLowerCase()}
        </span>
      ))}
    </span>
  )
}

export function SeverityChip({
  severity,
  children,
}: {
  severity: ImportIssueSeverity
  children?: React.ReactNode
}) {
  return (
    <span
      className={`inline-block rounded px-1.5 py-0.5 text-xs font-medium ${SEVERITY_STYLES[severity]}`}
    >
      {children ?? SEVERITY_LABELS[severity]}
    </span>
  )
}
