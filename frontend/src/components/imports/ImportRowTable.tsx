// Paginated table of import rows for the batch review page.

import type { ImportRow } from '@/types/imports'
import { IssueBadges } from '@/components/imports/IssueBadges'
import { ReviewStatusBadge, RowClassBadge } from '@/components/imports/ReviewStatusBadge'

interface ImportRowTableProps {
  rows: ImportRow[]
  loading: boolean
  error: boolean
  emptyMessage: string
  onOpenRow: (row: ImportRow) => void
}

export function ImportRowTable({
  rows,
  loading,
  error,
  emptyMessage,
  onOpenRow,
}: ImportRowTableProps) {
  if (loading) {
    return <div className="card p-6 text-sm text-muted">Loading rows…</div>
  }
  if (error) {
    return (
      <div className="card border-red-500/30 p-6 text-sm text-red-300">
        Could not load rows. Please try again.
      </div>
    )
  }
  if (rows.length === 0) {
    return <div className="card p-6 text-sm text-muted">{emptyMessage}</div>
  }

  return (
    <div className="card overflow-x-auto">
      <table className="w-full min-w-[640px] text-left text-sm">
        <thead className="border-b border-line text-xs uppercase tracking-wide text-muted">
          <tr>
            <th className="px-4 py-2 font-medium">Reference</th>
            <th className="px-4 py-2 font-medium">Customer name</th>
            <th className="px-4 py-2 font-medium">Class</th>
            <th className="px-4 py-2 font-medium">Status</th>
            <th className="px-4 py-2 font-medium">Issues</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const name =
              (typeof row.parsed?.customer_name === 'string' && row.parsed.customer_name) || ''
            return (
              <tr
                key={row.id}
                onClick={() => onOpenRow(row)}
                className="cursor-pointer border-b border-line/60 last:border-0 hover:bg-elevated"
              >
                <td className="px-4 py-2 font-mono text-xs text-fg">
                  {row.legacy_reference || <span className="text-faint">—</span>}
                </td>
                <td className="px-4 py-2 text-fg">
                  {name || <span className="text-faint">—</span>}
                </td>
                <td className="px-4 py-2">
                  <RowClassBadge rowClass={row.row_class} />
                </td>
                <td className="px-4 py-2">
                  <ReviewStatusBadge status={row.review_status} />
                </td>
                <td className="px-4 py-2">
                  <IssueBadges issues={row.issues} />
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
