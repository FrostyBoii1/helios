// Job status display: human labels + color-coded badge. Single source of truth
// for the status option list used by dropdowns.

import type { JobStatus } from '@/types'

// eslint-disable-next-line react-refresh/only-export-components -- display lookup co-located with its badge
export const JOB_STATUS_LABELS: Record<JobStatus, string> = {
  new: 'New',
  awaiting_approval: 'Awaiting approval',
  ready_to_schedule: 'Ready to schedule',
  booked_for_install: 'Booked for install',
  installed: 'Installed',
  post_install_call_required: 'Post-install call required',
  review_request_required: 'Review request required',
  maintenance_required: 'Maintenance required',
  support: 'Support',
  completed: 'Completed',
  cancelled: 'Cancelled',
}

// eslint-disable-next-line react-refresh/only-export-components -- display lookup co-located with its badge
export const JOB_STATUS_ORDER: JobStatus[] = [
  'new',
  'awaiting_approval',
  'ready_to_schedule',
  'booked_for_install',
  'installed',
  'post_install_call_required',
  'review_request_required',
  'maintenance_required',
  'support',
  'completed',
  'cancelled',
]

// Dark-tuned status chips: translucent tint background + bright text + ring.
const STATUS_CLASSES: Record<JobStatus, string> = {
  new: 'bg-slate-500/15 text-slate-300 ring-slate-400/20',
  awaiting_approval: 'bg-amber-500/15 text-amber-300 ring-amber-400/20',
  ready_to_schedule: 'bg-sky-500/15 text-sky-300 ring-sky-400/20',
  booked_for_install: 'bg-indigo-500/15 text-indigo-300 ring-indigo-400/20',
  installed: 'bg-emerald-500/15 text-emerald-300 ring-emerald-400/20',
  post_install_call_required: 'bg-cyan-500/15 text-cyan-300 ring-cyan-400/20',
  review_request_required: 'bg-violet-500/15 text-violet-300 ring-violet-400/20',
  maintenance_required: 'bg-orange-500/15 text-orange-300 ring-orange-400/20',
  support: 'bg-rose-500/15 text-rose-300 ring-rose-400/20',
  completed: 'bg-green-500/15 text-green-300 ring-green-400/20',
  cancelled: 'bg-slate-600/20 text-slate-400 ring-slate-500/20',
}

export function JobStatusBadge({ status }: { status: JobStatus }) {
  return (
    <span
      className={`inline-block whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${STATUS_CLASSES[status]}`}
    >
      {JOB_STATUS_LABELS[status]}
    </span>
  )
}
