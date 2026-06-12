// Job status display: human labels + color-coded badge. Single source of truth
// for the status option list used by dropdowns.

import type { JobStatus } from '@/types'

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

const STATUS_CLASSES: Record<JobStatus, string> = {
  new: 'bg-slate-100 text-slate-700',
  awaiting_approval: 'bg-amber-100 text-amber-800',
  ready_to_schedule: 'bg-sky-100 text-sky-800',
  booked_for_install: 'bg-indigo-100 text-indigo-800',
  installed: 'bg-emerald-100 text-emerald-800',
  post_install_call_required: 'bg-cyan-100 text-cyan-800',
  review_request_required: 'bg-violet-100 text-violet-800',
  maintenance_required: 'bg-orange-100 text-orange-800',
  support: 'bg-rose-100 text-rose-800',
  completed: 'bg-green-100 text-green-800',
  cancelled: 'bg-slate-200 text-slate-500',
}

export function JobStatusBadge({ status }: { status: JobStatus }) {
  return (
    <span
      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_CLASSES[status]}`}
    >
      {JOB_STATUS_LABELS[status]}
    </span>
  )
}
