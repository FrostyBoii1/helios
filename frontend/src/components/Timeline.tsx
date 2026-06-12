// Read-only activity timeline. Renders the append-only audit trail for a
// customer (includes its jobs' events) or a single job. Dark SunCentral theme.

import { JOB_STATUS_LABELS } from '@/components/JobStatusBadge'
import { useActivities } from '@/hooks/useActivities'
import type { Activity, JobStatus } from '@/types'

interface TimelineProps {
  customerId?: number
  jobId?: number
  title?: string
}

export function Timeline({ customerId, jobId, title = 'Timeline' }: TimelineProps) {
  const { data, isLoading, isError } = useActivities({
    customer_id: customerId,
    job_id: jobId,
    limit: 50,
  })

  const items = data?.items ?? []

  return (
    <div className="card p-5">
      <h2 className="eyebrow mb-4">
        {title}
        {data ? ` (${data.total})` : ''}
      </h2>

      {isLoading ? (
        <p className="text-sm text-muted">Loading activity…</p>
      ) : isError ? (
        <p className="text-sm text-red-400">Failed to load activity.</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-faint">No activity yet.</p>
      ) : (
        <ol className="relative ml-1 space-y-4 border-l border-line pl-5">
          {items.map((a) => (
            <li key={a.id} className="relative">
              <span
                className={`absolute -left-[1.6rem] top-1 h-2.5 w-2.5 rounded-full ring-2 ring-surface ${dotColor(a)}`}
                aria-hidden
              />
              <p className="text-sm text-fg">{a.description}</p>
              {formatMeta(a) && <p className="mt-0.5 text-xs text-muted">{formatMeta(a)}</p>}
              <p className="mt-0.5 text-xs text-faint">
                {a.actor ? a.actor.full_name : 'System'} · {formatTime(a.created_at)}
              </p>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}

function dotColor(a: Activity): string {
  const t = a.activity_type
  if (t.endsWith('deleted')) return 'bg-red-400'
  if (t === 'job_status_changed') return 'bg-violet-400'
  if (t === 'install_rescheduled') return 'bg-amber-400'
  if (t.startsWith('customer')) return 'bg-sky-400'
  if (t.startsWith('job')) return 'bg-brand-500'
  return 'bg-slate-400'
}

function formatTime(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

// Render a few common metadata cases as readable text. Raw meta is always
// available on the API; this is purely presentational sugar.
function formatMeta(a: Activity): string | null {
  const meta = a.meta
  if (!meta) return null

  if (a.activity_type === 'job_status_changed' && 'from' in meta && 'to' in meta) {
    return `${labelStatus(meta.from)} → ${labelStatus(meta.to)}`
  }
  if (a.activity_type === 'install_rescheduled' && 'from' in meta && 'to' in meta) {
    return `${String(meta.from)} → ${String(meta.to)}`
  }
  if (Array.isArray((meta as { changes?: unknown }).changes)) {
    return `Changed: ${((meta as { changes: unknown[] }).changes).join(', ')}`
  }
  return null
}

function labelStatus(value: unknown): string {
  const key = String(value) as JobStatus
  return JOB_STATUS_LABELS[key] ?? String(value)
}
