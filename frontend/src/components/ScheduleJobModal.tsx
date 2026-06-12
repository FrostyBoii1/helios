// Popup for a job on the weekly schedule board (scheduled or unscheduled):
// job summary, current install date, a set/reschedule control for admin /
// scheduling, and a link to the job detail.

import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '@/auth/AuthContext'
import { canEditJobInstallDate } from '@/auth/permissions'
import { JobStatusBadge } from '@/components/JobStatusBadge'
import { useUpdateJob } from '@/hooks/useJobs'
import type { Job } from '@/types'

export function ScheduleJobModal({ job, onClose }: { job: Job; onClose: () => void }) {
  const { user } = useAuth()
  const canReschedule = canEditJobInstallDate(user?.role.name)
  const [date, setDate] = useState(job.install_date ?? '')
  const [error, setError] = useState<string | null>(null)
  const updateMutation = useUpdateJob(job.id)

  async function save() {
    setError(null)
    const next = date || null
    if ((job.install_date ?? null) === next) {
      onClose()
      return
    }
    try {
      await updateMutation.mutateAsync({ install_date: next })
      onClose()
    } catch {
      setError('Could not update the install date.')
    }
  }

  return (
    <div
      className="fixed inset-0 z-20 flex items-center justify-center bg-black/60 px-4"
      role="dialog"
      aria-modal="true"
    >
      <div className="card w-full max-w-md p-6 shadow-2xl shadow-black/40">
        <div className="mb-1 flex items-center gap-3">
          <h2 className="font-mono text-lg font-semibold text-fg">{job.case_number}</h2>
          <JobStatusBadge status={job.status} />
        </div>
        <p className="mb-4 text-sm text-muted">
          {job.title ?? 'Untitled job'} · {job.customer.full_name}
        </p>

        {error && (
          <div className="mb-4 rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
            {error}
          </div>
        )}

        <div className="mb-4">
          <span className="eyebrow mb-1 block">Install date</span>
          {canReschedule ? (
            <input
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              className="input"
            />
          ) : (
            <p className="text-fg">{job.install_date ?? 'Not scheduled'}</p>
          )}
        </div>

        <div className="flex items-center justify-between">
          <Link
            to={`/jobs/${job.id}`}
            className="text-sm text-brand-400 underline hover:text-brand-500"
          >
            Open job
          </Link>
          <div className="flex gap-3">
            <button onClick={onClose} className="btn-secondary text-sm">
              Close
            </button>
            {canReschedule && (
              <button onClick={save} disabled={updateMutation.isPending} className="btn-primary text-sm">
                {updateMutation.isPending ? 'Saving…' : 'Save date'}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
