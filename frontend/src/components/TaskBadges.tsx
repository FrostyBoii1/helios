// Task status + priority chips, dark-tuned. Single source of truth for labels
// and the ordered option lists used by dropdowns.

import type { TaskPriority, TaskStatus } from '@/types'

export const TASK_STATUS_LABELS: Record<TaskStatus, string> = {
  open: 'Open',
  in_progress: 'In progress',
  completed: 'Completed',
  cancelled: 'Cancelled',
}

export const TASK_PRIORITY_LABELS: Record<TaskPriority, string> = {
  low: 'Low',
  normal: 'Normal',
  high: 'High',
  urgent: 'Urgent',
}

export const TASK_STATUS_ORDER: TaskStatus[] = ['open', 'in_progress', 'completed', 'cancelled']
export const TASK_PRIORITY_ORDER: TaskPriority[] = ['low', 'normal', 'high', 'urgent']

const STATUS_CLASSES: Record<TaskStatus, string> = {
  open: 'bg-sky-500/15 text-sky-300 ring-sky-400/20',
  in_progress: 'bg-indigo-500/15 text-indigo-300 ring-indigo-400/20',
  completed: 'bg-green-500/15 text-green-300 ring-green-400/20',
  cancelled: 'bg-slate-600/20 text-slate-400 ring-slate-500/20',
}

const PRIORITY_CLASSES: Record<TaskPriority, string> = {
  low: 'bg-slate-500/15 text-slate-300 ring-slate-400/20',
  normal: 'bg-slate-500/15 text-slate-300 ring-slate-400/20',
  high: 'bg-amber-500/15 text-amber-300 ring-amber-400/20',
  urgent: 'bg-red-500/15 text-red-300 ring-red-400/20',
}

const CHIP = 'inline-block whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset'

export function TaskStatusBadge({ status }: { status: TaskStatus }) {
  return <span className={`${CHIP} ${STATUS_CLASSES[status]}`}>{TASK_STATUS_LABELS[status]}</span>
}

export function TaskPriorityBadge({ priority }: { priority: TaskPriority }) {
  return (
    <span className={`${CHIP} ${PRIORITY_CLASSES[priority]}`}>
      {TASK_PRIORITY_LABELS[priority]}
    </span>
  )
}
