// Job label chips (Phase L2): show a job's operational labels near its status,
// with add/remove for users who may manage them. System labels (approval /
// decommission) render as chips but are never manually removable.

import { useState } from 'react'

import { useAuth } from '@/auth/AuthContext'
import { canManageJobLabels } from '@/auth/permissions'
import {
  useAssignJobLabel,
  useJobLabels,
  useLabelDefinitions,
  useRemoveJobLabel,
} from '@/hooks/useJobLabels'

// Map a label's colour token to a dark-tuned translucent chip style.
const SLATE = 'bg-slate-500/15 text-slate-300 ring-slate-400/25'
const COLOR_CLASSES: Record<string, string> = {
  green: 'bg-emerald-500/15 text-emerald-300 ring-emerald-400/25',
  amber: 'bg-amber-500/15 text-amber-300 ring-amber-400/25',
  red: 'bg-red-500/15 text-red-300 ring-red-400/25',
  orange: 'bg-orange-500/15 text-orange-300 ring-orange-400/25',
  blue: 'bg-sky-500/15 text-sky-300 ring-sky-400/25',
  slate: SLATE,
}

function colorClass(token: string): string {
  return COLOR_CLASSES[token] ?? SLATE
}

export function JobLabelChips({ jobId }: { jobId: number }) {
  const { user } = useAuth()
  const canManage = canManageJobLabels(user?.role.name)
  const { data: labels } = useJobLabels(jobId)
  const { data: definitions } = useLabelDefinitions()
  const assign = useAssignJobLabel(jobId)
  const remove = useRemoveJobLabel(jobId)
  const [picking, setPicking] = useState(false)

  const assigned = labels ?? []
  const assignedKeys = new Set(assigned.map((a) => a.label.key))
  // Addable = non-system definitions not already on the job.
  const addable = (definitions ?? []).filter((d) => !d.is_system && !assignedKeys.has(d.key))

  // Nothing to show for a viewer with no labels.
  if (assigned.length === 0 && !canManage) return null

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="eyebrow mr-1 text-faint">Labels</span>

      {assigned.map((a) => {
        const removable = canManage && !a.label.is_system
        // Operational labels sit a touch more muted than system (approval/decom).
        const muted = a.label.category === 'operational' ? 'opacity-90' : ''
        return (
          <span
            key={a.id}
            title={a.note ?? a.label.description ?? a.label.name}
            className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${colorClass(
              a.label.color,
            )} ${muted}`}
          >
            {a.label.name}
            {removable && (
              <button
                type="button"
                onClick={() => remove.mutate(a.label.key)}
                disabled={remove.isPending}
                aria-label={`Remove ${a.label.name}`}
                className="ml-0.5 rounded-full px-0.5 leading-none text-current/70 hover:bg-white/15 hover:text-current"
              >
                ×
              </button>
            )}
          </span>
        )
      })}

      {assigned.length === 0 && <span className="text-xs text-faint">none</span>}

      {canManage &&
        (picking ? (
          <select
            autoFocus
            defaultValue=""
            disabled={assign.isPending}
            onChange={(e) => {
              const key = e.target.value
              if (key) {
                assign.mutate(key)
                setPicking(false)
              }
            }}
            onBlur={() => setPicking(false)}
            className="input h-6 py-0 text-xs"
          >
            <option value="" disabled>
              Add label…
            </option>
            {addable.map((d) => (
              <option key={d.key} value={d.key}>
                {d.name}
              </option>
            ))}
          </select>
        ) : (
          addable.length > 0 && (
            <button
              type="button"
              onClick={() => setPicking(true)}
              className="rounded-full border border-dashed border-line-strong px-2 py-0.5 text-xs text-muted hover:border-line hover:text-fg"
            >
              + Label
            </button>
          )
        ))}
    </div>
  )
}
