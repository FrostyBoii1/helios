// Network-approval control: the authoritative way to view/edit a job's approval
// state. Approval is structured state ("label is law"), not a free-text note.
// Shown under the structured details (Electrical / network area). In read mode it
// shows the current state so approval is visible before pressing Edit; in edit
// mode (for permitted users) it shows the editable control.

import { useState } from 'react'

import { useAuth } from '@/auth/AuthContext'
import { canSetJobApproval } from '@/auth/permissions'
import { useJobLabels, useSetJobApproval } from '@/hooks/useJobLabels'
import type { Job, JobApprovalState } from '@/types'

function currentState(keys: Set<string>): JobApprovalState {
  if (keys.has('approval_approved')) return 'approved'
  if (keys.has('approval_pending')) return 'pending'
  if (keys.has('approval_required')) return 'required'
  return 'none'
}

const READ_LABEL: Record<JobApprovalState, string> = {
  none: 'Not applicable',
  required: 'Needs approval',
  pending: 'Pending approval',
  approved: 'Approved',
}

export function JobApprovalControl({
  job,
  editing,
  onSaved,
}: {
  job: Job
  editing: boolean
  // Optional: called after a successful approval set (H5D lets the parent collapse the editor).
  // Purely a UX hook — the mutation and business rules are unchanged whether or not it is provided.
  onSaved?: () => void
}) {
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

  const dirty = state !== cur || (state === 'pending' && pendingDate !== curPending)
  const showEditor = editing && canEdit

  return (
    <div className="rounded-md border border-line bg-elevated p-3">
      <h4 className="eyebrow mb-2 text-faint">Network approval</h4>

      {showEditor ? (
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
              <option value="none">No approval / not applicable</option>
              <option value="required">Needs approval</option>
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
              setApproval.mutate(
                {
                  state,
                  pending_date: state === 'pending' ? pendingDate || null : null,
                },
                { onSuccess: () => onSaved?.() },
              )
            }
            disabled={!dirty || setApproval.isPending}
            className="btn-primary px-3 py-1 text-sm"
          >
            Set approval
          </button>
        </div>
      ) : (
        <p className="text-sm text-fg">
          {READ_LABEL[cur]}
          {cur === 'pending' && curPending ? ` — ${curPending}` : ''}
        </p>
      )}
    </div>
  )
}
