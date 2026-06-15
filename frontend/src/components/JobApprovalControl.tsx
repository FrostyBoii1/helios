// Dedicated approval control (Slice 2): the authoritative way to edit a job's
// approval state. Approval is structured state ("label is law"), not a free-text
// note — so this replaces the old approval_details textarea on structured jobs.

import { useState } from 'react'

import { useAuth } from '@/auth/AuthContext'
import { canSetJobApproval } from '@/auth/permissions'
import { useJobLabels, useSetJobApproval } from '@/hooks/useJobLabels'
import type { Job, JobApprovalState } from '@/types'

function currentState(keys: Set<string>): JobApprovalState {
  if (keys.has('approval_approved')) return 'approved'
  if (keys.has('approval_pending')) return 'pending'
  return 'none'
}

export function JobApprovalControl({ job }: { job: Job }) {
  const { user } = useAuth()
  const canEdit = canSetJobApproval(user?.role.name)
  const { data: labels } = useJobLabels(job.id)
  const setApproval = useSetJobApproval(job.id)

  const keys = new Set((labels ?? []).map((a) => a.label.key))
  const cur = currentState(keys)
  const curPending =
    (job.details?.approval as { pending_date?: string | null } | undefined)?.pending_date ?? ''

  const [state, setState] = useState<JobApprovalState>(cur)
  const [pendingDate, setPendingDate] = useState(curPending)

  // Only writers see the control; everyone else sees approval via the chip.
  if (!canEdit) return null

  const dirty = state !== cur || (state === 'pending' && pendingDate !== curPending)

  return (
    <div className="rounded-md border border-line bg-elevated p-3">
      <h4 className="eyebrow mb-2 text-faint">Approval</h4>
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <label htmlFor="approval-state" className="block text-xs text-faint">
            State
          </label>
          <select
            id="approval-state"
            value={state}
            onChange={(e) => setState(e.target.value as JobApprovalState)}
            className="input mt-1 text-sm"
          >
            <option value="none">No approval</option>
            <option value="pending">Pending approval</option>
            <option value="approved">Approved</option>
          </select>
        </div>

        {state === 'pending' && (
          <div>
            <label htmlFor="approval-pending-date" className="block text-xs text-faint">
              Pending date
            </label>
            <input
              id="approval-pending-date"
              value={pendingDate}
              onChange={(e) => setPendingDate(e.target.value)}
              placeholder="dd/mm/yyyy"
              className="input mt-1 px-2 py-1 text-sm"
            />
          </div>
        )}

        <button
          type="button"
          onClick={() =>
            setApproval.mutate({
              state,
              pending_date: state === 'pending' ? pendingDate || null : null,
            })
          }
          disabled={!dirty || setApproval.isPending}
          className="btn-primary px-3 py-1 text-sm"
        >
          Set approval
        </button>
      </div>
      <p className="mt-2 text-xs text-faint">
        Approval state is shown as a chip near the status. No approval = not applicable (no label).
      </p>
    </div>
  )
}
